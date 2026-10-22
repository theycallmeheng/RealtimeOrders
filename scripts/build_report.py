"""Build the course paper from this project's measured evidence only.
Run with the bundled document Python runtime (python-docx and Pillow).
"""
import json
import statistics
from pathlib import Path
import xml.etree.ElementTree as ET
from PIL import Image,ImageDraw,ImageFont
from docx import Document
from docx.shared import Inches,Pt,RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT=Path(__file__).resolve().parents[1]

def table(doc,headers,records,widths):
    t=doc.add_table(rows=1,cols=len(headers));t.autofit=False
    for i,w in enumerate(widths):t.columns[i].width=Inches(w)
    for cell,value in zip(t.rows[0].cells,headers):
        cell.text=str(value);shd=OxmlElement('w:shd');shd.set(qn('w:fill'),'DCE6F1');cell._tc.get_or_add_tcPr().append(shd)
        for run in cell.paragraphs[0].runs:run.bold=True
    repeat=OxmlElement('w:tblHeader');t.rows[0]._tr.get_or_add_trPr().append(repeat)
    for record in records:
        for c,v in zip(t.add_row().cells,record):c.text=str(v)
    for row in t.rows:
        cant=OxmlElement('w:cantSplit');row._tr.get_or_add_trPr().append(cant)
        for i,cell in enumerate(row.cells):
            cell.width=Inches(widths[i]);cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
            props=cell._tc.get_or_add_tcPr();borders=OxmlElement('w:tcBorders')
            for edge in ('top','bottom','left','right'):
                e=OxmlElement('w:'+edge);e.set(qn('w:val'),'single');e.set(qn('w:sz'),'5');e.set(qn('w:color'),'D9D9D9');borders.append(e)
            props.append(borders);margins=OxmlElement('w:tcMar')
            for edge in ('top','bottom','left','right'):
                e=OxmlElement('w:'+edge);e.set(qn('w:w'),'85');e.set(qn('w:type'),'dxa');margins.append(e)
            props.append(margins)
            for p in cell.paragraphs:
                p.paragraph_format.space_after=Pt(3);p.paragraph_format.space_before=Pt(3);p.paragraph_format.line_spacing=1.05
                if i and len(cell.text)<24:p.alignment=WD_ALIGN_PARAGRAPH.CENTER
                for r in p.runs:r.font.size=Pt(10)
    doc.add_paragraph().paragraph_format.space_after=Pt(2)

def diagram():
    path=ROOT/'docs/architecture.png';image=Image.new('RGB',(1300,480),'white');draw=ImageDraw.Draw(image)
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',26);small=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',22)
    boxes=[(20,60,280,250),(345,60,625,250),(690,60,970,250),(1040,60,1280,250)]
    labels=['Browser\nNext.js UI\nCustomer / Admin','TLS proxy\nHTTPS REST\nWSS JSON v1','FastAPI\nAuth / Transactions\nOne worker','MySQL InnoDB\nDomain data\nEvents / Outbox']
    for b,label in zip(boxes,labels):draw.rectangle(b,outline='#64748b',width=2);draw.multiline_text(((b[0]+b[2])/2,155),label,font=font,fill='black',anchor='mm',align='center',spacing=14)
    for a,b in [(280,345),(625,690),(970,1040)]:
        draw.line((a+3,155,b-8,155),fill='black',width=3);draw.polygon([(b-8,155),(b-20,147),(b-20,163)],fill='black')
    draw.line((1160,255,1160,350,820,350,820,255),fill='black',width=3);draw.polygon([(820,255),(812,269),(828,269)],fill='black')
    draw.text((970,392),'Durable outbox -> bounded topic hub',font=small,fill='black',anchor='mm')
    draw.text((325,340),'Commit before ACK / publication',font=small,fill='black',anchor='mm')
    draw.text((325,390),'Snapshot / replay / stable operation IDs',font=small,fill='black',anchor='mm')
    image.save(path);return path

def main():
    loads=[json.loads(p.read_text(encoding='utf-8'))|{'file':p.name} for p in (ROOT/'evidence/load').glob('*.json')]
    comparisons=[json.loads(p.read_text(encoding='utf-8')) for p in (ROOT/'evidence/comparison').glob('*.json')]
    valid=[d for d in comparisons if d.get('validTiming')]
    assert valid,'Final comparison with correct warmup timing gate is required'
    comparison=valid[-1]
    optimized=[d for d in loads if d.get('variant')=='batched-session-check']
    assert optimized,'Final load run after session batching is required'
    final=max(optimized,key=lambda d:d['requestedDistinctCustomers'])
    junit=ET.parse(ROOT/'evidence/integration.xml').getroot()
    suites=list(junit.iter('testsuite'));tests=sum(int(s.get('tests',0)) for s in suites);failures=sum(int(s.get('failures',0))+int(s.get('errors',0)) for s in suites)
    browser=json.loads((ROOT/'evidence/browser-results.json').read_text(encoding='utf-8'))
    team=json.loads((ROOT/'docs/team.json').read_text(encoding='utf-8'))
    restore=json.loads((ROOT/'evidence/restore-check.json').read_text(encoding='utf-8'))
    doc=Document();section=doc.sections[0];section.page_width=Inches(8.5);section.page_height=Inches(11)
    section.top_margin=section.bottom_margin=Inches(.75);section.left_margin=section.right_margin=Inches(.85)
    for name,size in [('Normal',11),('Title',25),('Subtitle',12),('Heading 1',16),('Heading 2',12)]:
        style=doc.styles[name];style.font.name='Calibri';style.font.size=Pt(size);style.font.color.rgb=RGBColor(0,0,0)
        style.font.bold=name in ('Title','Heading 1','Heading 2');style.font.cs_bold=style.font.bold
        style.font.italic=False;style.font.cs_italic=False;style.font.underline=False
        style.paragraph_format.space_after=Pt(7);style.paragraph_format.line_spacing=1.1
        fonts=style._element.get_or_add_rPr().rFonts
        for attr in ('asciiTheme','hAnsiTheme','eastAsiaTheme','cstheme'):
            fonts.attrib.pop(qn('w:'+attr),None)
        for attr in ('ascii','hAnsi','eastAsia','cs'):fonts.set(qn('w:'+attr),'Calibri')
        for border in style._element.xpath('.//w:pBdr'):border.getparent().remove(border)
    for numbering in doc.styles['Subtitle']._element.xpath('.//w:numPr'):numbering.getparent().remove(numbering)
    for fonts in doc.styles.element.xpath('./w:docDefaults/w:rPrDefault/w:rPr/w:rFonts'):
        for attr in ('asciiTheme','hAnsiTheme','eastAsiaTheme','cstheme'):fonts.attrib.pop(qn('w:'+attr),None)
        for attr in ('ascii','hAnsi','eastAsia','cs'):fonts.set(qn('w:'+attr),'Calibri')
    for name in ('Heading 1','Heading 2'):doc.styles[name].paragraph_format.keep_with_next=True
    footer=section.footer.paragraphs[0];footer.alignment=WD_ALIGN_PARAGRAPH.CENTER
    field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');footer._p.append(field)
    def h(s):doc.add_heading(s,1)
    def p(s):doc.add_paragraph(s)
    def page():doc.add_page_break()
    def code(s):
        for line in s.splitlines():
            para=doc.add_paragraph();para.paragraph_format.space_after=Pt(0);para.paragraph_format.line_spacing=1
            run=para.add_run(line);run.font.name='Courier New';run.font.size=Pt(9)
    doc.core_properties.title='RealtimeOrders Hệ thống đặt hàng thời gian thực'
    doc.core_properties.author='Nhóm 17'
    doc.add_paragraph('RealtimeOrders',style='Title')
    doc.add_paragraph('Hệ thống đặt hàng và điều phối bán hàng thời gian thực',style='Subtitle')
    p('Bài tập lớn Lập trình mạng năm học 2026–2027\nNhóm 17 · Giảng viên Ngô Văn Quyền · Ngày 22 tháng 10 năm 2026')
    table(doc,['Thành viên','Mã sinh viên'],[(m['name'],m['studentId']) for m in team['members']],[4.4,2.2])
    h('Tóm tắt')
    p(f'RealtimeOrders giải quyết việc bán hàng theo đợt có lượng tồn hữu hạn, giá và giao hàng theo nhóm khách. Ứng dụng dùng Next.js, Python FastAPI, MySQL InnoDB và HTTPS/WSS. Server quyết định giá, phân quyền, duyệt nguyên đơn và lưu dữ liệu cùng sự kiện trước khi trả kết quả. Kiểm thử thực tế có {tests} ca Python, {failures} lỗi; kiểm thử trình duyệt có {browser["stats"]["expected"]} kịch bản đạt. Phép tạo tải dùng khách khác nhau, đo riêng số kết nối, tốc độ đọc và độ trễ; kết quả không được diễn giải thành hàng nghìn người cùng đặt đơn mỗi giây. Đóng góp chính là nhất quán tồn kho, cập nhật theo nhóm giá và phục hồi không tạo bản sao.')
    p('Từ khóa: lập trình mạng; WebSocket; client server; InnoDB; idempotency; transactional outbox.')

    page();h('1 Giới thiệu')
    p('Khi người bán chốt đơn bằng tin nhắn rời rạc, khách khó biết trạng thái và người bán dễ nhận quá lượng hàng hiện có. Hệ thống tập trung danh mục trong ngày, chính sách giao, duyệt đơn và trao đổi riêng để người mua có thông tin nhất quán. Giá trị sử dụng cần được đánh giá thêm với người dùng thật; báo cáo không tự khai mức hài lòng hay hiệu quả kinh doanh chưa được đo.')
    p('Mục tiêu là bảo đảm nhiều người gửi yêu cầu cùng lúc không làm sai kho, trạng thái có thể phục hồi sau mất kết nối và dữ liệu riêng chỉ tới đúng người. Đây là ứng dụng web một người bán, hai vai trò chính, có nhóm sinh viên và người đi làm. Thanh toán COD, không có cổng thanh toán hoặc tích hợp hãng vận chuyển.')
    h('2 Kiến thức nền và công trình liên quan')
    p('HTTP phù hợp với thao tác có kết quả request/response, trong khi WebSocket duy trì kênh hai chiều để server đẩy cập nhật [1]. Framework xử lý TCP, TLS và framing; protocol ứng dụng phải tự xác định danh tính, dữ liệu, thứ tự và phục hồi. Registry trong RAM chỉ phù hợp một worker nếu chưa có bus dùng chung.')
    p('InnoDB locking read cho phép kiểm tra và thay đổi một bản ghi trong giao dịch có khóa [2]. SQLAlchemy yêu cầu session riêng cho mỗi tác vụ đồng thời [3]. Thiết kế dùng các nguyên lý đã có, không tuyên bố phát minh WebSocket, row lock hay outbox. Baseline thực nghiệm là polling toàn working set mỗi hai giây do nhóm tự xây.')
    h('3 Định nghĩa bài toán')
    p('Đầu vào gồm tài khoản, nhóm giá, địa chỉ, sản phẩm, đợt hàng, đơn, yêu cầu và tin nhắn. Đầu ra gồm đơn đúng giá, tồn kho nhất quán, lịch sử, thông báo và báo cáo doanh thu. Server là nguồn dữ liệu có thẩm quyền; trình duyệt không truy cập MySQL trực tiếp.')
    table(doc,['Ràng buộc','Cách áp dụng'],[
      ('Tồn kho hữu hạn','PENDING không giữ hàng; duyệt kiểm tra lại toàn bộ dòng'),
      ('Danh tính và quyền','OTP SĐT, phiên cookie, role và group từ server'),
      ('Giá và giao hàng','Snapshot tại lúc đặt; version đổi yêu cầu xác nhận lại'),
      ('Dữ liệu riêng','Topic catalog theo nhóm, user riêng và admin ops'),
      ('Lỗi mạng','Request ID ổn định, replay hoặc snapshot sau kết nối lại')],[1.7,4.9])

    page();h('4 Giải pháp và kiến trúc hệ thống')
    p('Trình duyệt truy cập một origin HTTPS. Proxy chuyển REST và WSS tới FastAPI, nội dung giao diện tới Next.js. Backend dùng giao dịch MySQL; outbox đọc sự kiện đã commit và đẩy vào topic hub có hàng đợi riêng từng socket. Người nhận chậm không chặn vòng phát của người khác.')
    doc.add_picture(str(diagram()),width=Inches(6.6));p('Hình 1 Kiến trúc triển khai một worker trên máy thử')
    p('Với mỗi thay đổi chính thức, server lưu trạng thái, lịch sử, khóa idempotency và sự kiện trong cùng giao dịch. Chỉ sau commit API mới trả thành công; outbox cũng chỉ đọc được sự kiện đã commit. Sự kiện có thể phát lặp sau sự cố, vì vậy client phải loại trùng bằng seq theo topic.')
    p('Tồn kho được khóa theo thứ tự ID để hạn chế vòng chờ. Thay đổi ở hai đơn vẫn có thể cạnh tranh cùng đợt hàng; mọi dòng phải đủ trước khi ghi ledger và giảm tồn. Server không gọi SMS hoặc chờ mạng trong vùng khóa kho.')
    h('5 Luồng xử lý chính')
    p('Khách xác minh SĐT, đăng ký, đăng nhập và thêm địa chỉ. Danh mục chỉ trả giá nhóm hiện hành. Đơn gửi thành công ở PENDING; admin duyệt chuyển APPROVED và trừ kho. Các bước tiếp theo là PREPARING, SHIPPING và DELIVERED. Khách xin hủy trước SHIPPING; khi được chấp thuận, ledger hoàn kho được ghi một lần.')
    p('Yêu cầu hàng có vòng đời riêng: NEW, RECEIVED, QUOTED, ACCEPTED, CONVERTED. Báo giá có phiên bản và hạn; khách đồng ý rồi tạo một đơn liên kết theo giá đã chấp thuận. Tiến trình giao hàng tiếp tục nằm trên đơn, tránh duy trì hai bộ trạng thái mâu thuẫn.')

    page();h('6 Thiết kế giao tiếp mạng')
    p('REST dùng JSON UTF 8 dưới /api/v1; số tiền và số lượng truyền dưới dạng chuỗi thập phân, seq và version là chuỗi số nguyên. Thao tác ghi yêu cầu Origin, CSRF và khi cần Idempotency Key. Server lấy người gửi từ phiên, bỏ qua giá hay vai trò do client tự khai.')
    code('POST /api/v1/orders\nIdempotency-Key: UUID\nX-CSRF-Token: session-csrf\n{\n  "clientOrderId": "UUID", "addressId": "UUID",\n  "deliveryMethod": "INDIVIDUAL", "policyVersion": "1",\n  "items": [{"offerId": "UUID", "quantity": "0.300",\n             "expectedPriceVersion": "1"}]\n}')
    p('WSS /ws xác thực cookie và Origin trước HELLO v1. Server cấp topic, client không tự đăng ký topic tùy ý. SYNC_BEGIN và các SNAPSHOT_CHUNK kết thúc bằng SYNC_END tại head nhất quán; sự kiện live được đăng ký trước khi đọc snapshot. Snapshot và heads đọc cùng REPEATABLE READ.')
    code('{"v":1,"type":"EVENT","topic":"catalog:GROUP_UUID",\n "seq":"12","eventId":"UUID",\n "eventType":"CATALOG_CHANGED",\n "payload":{"offers":[{"id":"UUID","version":"3",\n   "unit_price":"28000","available_qty":"12.500"}],\n   "removedOfferIds":[]}}')
    p('Payload catalog thực chứa các trường canonical, nhưng chỉ giá của nhóm nhận. Client áp dụng trực tiếp; thay đổi cấu hình diện rộng yêu cầu refresh. Kết nối lại có model/cursor hợp lệ thì replay tối đa 500 event hoặc 256 KiB; vượt giới hạn dùng snapshot. Reload không có model luôn snapshot.')
    p('Heartbeat 15 giây, stale 45 giây, reconnect 1/2/4/8/15 giây có jitter. Queue mỗi socket tối đa 128 frame hoặc 512 KiB; frame vượt 64 KiB đóng 1009, sai quyền 1008, người nhận chậm 1013. Kiểm tra phiên được gom theo lô mỗi hai giây; lệnh ghi vẫn xác thực riêng.')

    page();h('7 Giao dịch kho và khả năng phục hồi')
    code('BEGIN\n  claim idempotency key and verify request hash\n  lock affected customer and order\n  check expected order version and allowed transition\n  lock all offers in sorted ID order\n  verify every requested quantity fits remaining stock\n  write stock balances and unique inventory movements\n  write order status and history\n  allocate topic sequences and write events plus outbox\n  store canonical idempotent response\nCOMMIT\nreturn ACK or HTTP success')
    p('Nếu một dòng thiếu, toàn bộ giao dịch rollback. Ledger có khóa duy nhất theo loại, tham chiếu và đợt hàng; duyệt hoặc hoàn cùng đơn không thể tạo hai movement. Kiểm thử gửi lại cùng key sau mất ACK nhận lại kết quả đã lưu. Dùng cùng key với nội dung khác trả 409.')
    p('Bất biến kiểm tra là tồn cuối bằng tồn đầu cộng điều chỉnh trừ lượng đã duyệt cộng lượng đã hoàn; tồn không âm. Đơn PENDING chưa tạo movement trừ kho. Hủy và chuyển SHIPPING dùng khóa/version cùng aggregate; đang có yêu cầu hủy OPEN thì không bàn giao.')
    p('Mỗi topic có một stream head khóa trong giao dịch. B không lấy seq tiếp theo trước khi A giải phóng head; client không dùng auto increment outbox làm cursor. Sự kiện đã commit chưa phát còn trong DB sau restart. Nếu phát lặp, seq giúp loại trùng; client nhận chậm được đóng để đồng bộ lại thay vì tăng bộ nhớ vô hạn.')
    h('8 Cài đặt và bảo vệ dữ liệu')
    p('38 bảng nghiệp vụ dùng InnoDB, khóa ngoại và Decimal; Alembic quản lý migration đầu. SQLAlchemy Core phản chiếu schema, mỗi request/task có session riêng. Mật khẩu Argon2id, token phiên và OTP chỉ lưu hash/HMAC, email phải xác minh trước khi dùng đăng nhập. Tài khoản khóa/xóa mềm không xóa lịch sử.')
    p('Ảnh JPEG/PNG/WebP được giới hạn byte/pixel, giải mã và re encode; chat kiểm tra quyền trước khi đọc ảnh. Bộ lọc từ chạy server, lưu bản canonical đã che và log hạn chế quyền. Địa chỉ vi phạm được yêu cầu sửa để không làm sai thông tin giao. Adapter SMS Twilio/SMTP có triển khai, nhưng kết quả thực hiện trong báo cáo dùng demo có nhãn [4][5].')

    page();h('9 Thiết lập thực nghiệm')
    env=final['environment']
    p(f'Môi trường là Windows trên một máy có {env["cpuLogical"]} CPU logic và {env["ramGiB"]} GiB RAM; Python {env["python"]}, Node.js 24.19.0, Next.js 16.4.2, MySQL 8.0.46. Generator, proxy TLS, FastAPI một worker và MySQL cùng máy qua loopback. Đây không phải phép đo LAN nhiều máy hay kiểm định triển khai Internet.')
    p('Unit và integration chạy HTTPS/WSS thật với MySQL, không dùng SQLite để chứng minh khóa. Browser dùng Edge headless, hai context đăng nhập riêng và viewport 360 px. Chứng thư tự ký chỉ phục vụ thử; browser/generator bỏ kiểm tra chuỗi tin cậy trong môi trường kiểm soát.')
    p('Thử tải tăng từ 100 lên 500, 1000 và 2000 khách khác nhau, mỗi khách một phiên và một socket. Lượt đầu đo 30 giây, mức 2000 đo 60 giây sau khi đồng bộ. Tốc độ GET yêu cầu là 10/s trên toàn hệ thống; phải đọc cột tốc độ thực. Không có đặt hoặc duyệt hàng loạt trong workload này.')
    p(f'So sánh WSS với polling dùng {comparison["clients"]} khách ở hai nhóm giá, {comparison["benchmarkOfferCount"]} offer thử cùng danh mục mẫu. Producer đổi hai offer mỗi giây. Mỗi mode warmup {comparison["warmupSeconds"]} giây, đo {comparison["measurementSeconds"]} giây, lặp {comparison["repeats"]} lần; thứ tự mode xen kẽ. Phiên bản tạo trong warmup bị loại khỏi thống kê latency. Byte là payload JSON UTF 8, không bao gồm HTTP header, TLS hay bootstrap.')
    p('Độ trễ tính bằng cùng perf_counter từ trước giao dịch producer đến lúc observer parse phiên bản canonical; không trừ timestamp của hai máy, không gọi đây là độ trễ vẽ pixel của browser. p50/p95 lấy theo thứ hạng mẫu của từng run; không trung bình p95 rồi gọi là p95 gộp.')
    p('Dữ liệu gốc lưu trong evidence/load, evidence/comparison, JUnit XML, kết quả browser và restore check. Các lượt thăm dò có vấn đề về ranh giới warmup được giữ nhưng không dùng làm số liệu latency cuối. Ma trận 24 lượt với 60 giây cho mọi mức tải trong thiết kế ban đầu chưa được thực hiện đầy đủ.')

    page();h('10 Kết quả kiểm thử và tải kết nối')
    p(f'Bộ Python có {tests} ca, {failures} lỗi trong lượt cuối. Các nhóm quan trọng gồm OTP, phân quyền, giới hạn địa chỉ đồng thời, giá nhóm, số lượng Decimal, PENDING không trừ kho, cạnh tranh duyệt, all or nothing, hoàn đúng một lần, quote, chat ảnh, seq, snapshot/replay và queue. Browser đạt {browser["stats"]["expected"]} kịch bản gồm quy trình hai vai trò, mobile, offline/reconnect và xác nhận lại giá/phí.')
    records=[]
    for d in sorted(loads,key=lambda d:(bool(d.get('variant')),d['requestedDistinctCustomers'],d['timestampUtc'])):
        records.append([d['requestedDistinctCustomers'],'Theo lô' if d.get('variant') else 'Trước tối ưu',d['activeAtEnd'],round(d['successfulCatalogRequests']/d['measurementSeconds'],2),d['catalogP95Ms'],d['eventP95Ms']])
    table(doc,['Khách','Phiên bản','Còn nối','GET mỗi s','API p95 ms','Event p95 ms'],records,[.6,1.25,.65,.85,1.15,1.35])
    p(f'Lượt mới nhất duy trì {final["activeAtEnd"]}/{final["requestedDistinctCustomers"]} socket cuối giai đoạn đo. Có {len(final["errors"])} lỗi kỹ thuật được ghi trong raw; độ trễ cần đối chiếu mục tiêu 500 ms cho event và 1 giây cho API. Giữ được socket không tự chứng minh đạt tốc độ thao tác hoặc phục vụ kinh doanh ở cùng số khách.')
    if final.get('reconnectFraction'):
        p(f'Lượt này ngắt {int(final["reconnectFraction"]*100)}% socket sau giây 20, chờ năm giây rồi nối lại bằng snapshot. Công cụ ghi {final["recoveredConnections"]} kết nối phục hồi; p95 thời gian từ bắt đầu nối lại đến SYNC_END là {final["recoveryP95Ms"]} ms. Kết quả không bao gồm năm giây cố ý ngắt và không phải replay incremental.')
    p(f'Backup đã import vào database mới {restore["targetDatabase"]}, kiểm tra {len(restore["tables"])} bảng kể cả Alembic. Bảng nghiệp vụ đối chiếu dữ liệu; bảng nền có thể tiến triển sau dump. Media có danh sách hash để kiểm tra cùng bản sao. Không ghi đè database làm việc.')

    page();h('11 So sánh WSS và polling')
    records=[]
    for r in comparison['runs']:
        records.append([r['mode'].upper(),r['repeat'],r['requests'],round(r['bytes']/1048576,2),r['p95Ms'],f'{r["convergedClientsAfterDrain"]}/{r["clients"]}',r['errors']])
    table(doc,['Mode','Lần','GET','MiB JSON','p95 ms','Hội tụ','Lỗi'],records,[.85,.45,.6,1.05,1.05,.95,.7])
    w=[r for r in comparison['runs'] if r['mode']=='wss'];b=[r for r in comparison['runs'] if r['mode']=='polling']
    mean_w=statistics.mean(r['bytes'] for r in w);mean_b=statistics.mean(r['bytes'] for r in b);reduction=(1-mean_w/mean_b)*100
    p(f'Trong workload đã công bố, payload JSON trung bình mỗi run WSS thấp hơn polling {reduction:.1f}%. Con số này chỉ có ý nghĩa với kích thước working set, nhịp cập nhật và nhịp polling đang thử. Không suy ra mức tiết kiệm gói TCP/TLS hoặc so với mọi hệ thống bán hàng khác.')
    h('12 Thảo luận')
    p('Polling truyền lại danh mục dù chỉ một offer thay đổi; số GET và xử lý danh mục tăng theo số khách. WSS gửi thay đổi của đúng nhóm, bỏ các lần đọc lặp khi có event. Đổi lại, server giữ kết nối dài hạn, phải quản lý queue, phiên, thứ tự và phục hồi. Catalog nhỏ hoặc nhịp cập nhật cao có thể làm lợi ích byte nhỏ đi; các lượt thăm dò với ít offer cho thấy không thể mặc định WSS luôn ít byte hơn.')
    p('Kiểm tra phiên theo lô giảm truy vấn lặp ở hàng nghìn socket. Đây là tối ưu triển khai cần đo cùng dữ liệu và môi trường, không phải thay thế xác thực lệnh ghi. Các phép thử cùng máy chịu cạnh tranh CPU/RAM của generator và server; cần máy tạo tải riêng trước khi công bố năng lực triển khai thực tế.')
    p('Ngay cả khi không có lỗi HTTP, hệ thống vẫn có thể không đáp ứng tốc độ yêu cầu hoặc p95. Vì vậy báo cáo công bố tốc độ thực, độ trễ và số kết nối riêng. Quan sát cuối sau drain được dùng để kiểm tra trạng thái hội tụ; số bản cập nhật nhận ít hơn không tự được gọi là mất gói TCP.')

    page();h('13 Đóng góp kỹ thuật')
    table(doc,['Đóng góp','So với baseline','Bằng chứng'],[
      ('Nhất quán duyệt và hủy','Thay read then write không khóa bằng giao dịch kiểm tra nguyên đơn','Test cạnh tranh 7 và 7 trên kho 10, rollback nhiều dòng, ledger hoàn một lần'),
      ('Cập nhật theo nhóm giá','Thay polling toàn danh mục bằng phần thay đổi có quyền','So sánh ba lần lặp và kiểm thử không lộ giá nhóm khác'),
      ('Phục hồi bền vững','Thay trạng thái chỉ trong RAM bằng seq, event, outbox và mã ổn định','Test replay/snapshot, ACK trùng, restart, restore và reconnect browser')],[1.55,2.15,2.9])
    h('14 Giới hạn và hướng phát triển')
    p('SMS/email thật chưa được kiểm tra với nhà cung cấp; môi trường demo hiển thị mã có nhãn. Chưa nghiệm thu hai thiết bị LAN, khảo sát người mua hoặc tải nghiệp vụ 2000 khách đồng thời đặt/duyệt/chat. Chưa chạy đủ ma trận E1–E3 ban đầu. Không tuyên bố đã đạt kiểm định bảo mật, SLA hoặc mức tương đồng Compilatio.')
    p('Bản hiện tại chỉ một worker FastAPI, event giữ để truy vết, báo cáo tổng hợp UTC. Vận hành lâu dài cần retention, giám sát, backup ngoài máy và kiểm thử shared bus trước khi mở rộng nhiều worker. Triển khai thật cần chứng thư CA hợp lệ, domain, nhà cung cấp SMS, dữ liệu khu giao và chính sách nghiệp vụ do người bán xác nhận.')
    h('15 Kết luận')
    p('RealtimeOrders đã có ứng dụng web hai vai trò chạy qua HTTPS/WSS và MySQL. Phần cốt lõi thể hiện lập trình mạng ở protocol ứng dụng, quyền topic, điều khiển trạng thái đồng thời, hàng đợi và phục hồi. Bằng chứng thử nghiệm cho phép đánh giá rõ điểm đạt và giới hạn của từng workload; bước nghiệm thu thực địa phải tiếp tục trên dữ liệu và hạ tầng dự kiến sử dụng.')

    page();h('16 Minh họa giao diện và kịch bản demo')
    screenshot=ROOT/'evidence/customer-desktop.png'
    if screenshot.exists():
        with Image.open(screenshot) as im: ratio=im.height/im.width
        doc.add_picture(str(screenshot),width=Inches(min(6.6,4.6/ratio)))
    p('Hình 2 Danh mục theo nhóm giá và đơn đang soạn của khách')
    p('Demo đề nghị: mở hai phiên riêng cho khách và quản trị; khách thêm hàng và gửi đơn; quản trị duyệt, khách thấy trạng thái mới. Sau đó xin hủy trước SHIPPING, quản trị chấp thuận và đối chiếu ledger hoàn. Gửi tin nhắn có ảnh và thử từ cấm mẫu để quan sát canonical text, cảnh báo và nhật ký.')
    p('Để trình bày mạng: tắt kết nối trình duyệt khách, xác nhận khóa gửi mới, cập nhật ở phía quản trị rồi nối lại; đối chiếu snapshot hoặc replay. Thử hai đơn tranh kho để chỉ một đơn được duyệt. Trình bày Idempotency Key và seq bằng công cụ mạng của trình duyệt, không hiển thị token phiên hoặc mật khẩu khi quay demo.')
    p('Lệnh chạy, nguồn dữ liệu, hướng dẫn backup và các file số liệu nằm trong README và docs/OPERATIONS.md. Tài khoản demo sinh ngẫu nhiên, không ghi mật khẩu mặc định trong báo cáo hoặc gói source.')

    page();h('17 Tài liệu tham khảo')
    for ref in [
      '[1] FastAPI. WebSockets. https://fastapi.tiangolo.com/advanced/websockets/ Truy cập 22/10/2026.',
      '[2] Oracle. MySQL 8.4 Reference Manual, Locking Reads. https://dev.mysql.com/doc/refman/8.4/en/innodb-locking-reads.html Truy cập 22/10/2026.',
      '[3] SQLAlchemy. Asynchronous I O. https://docs.sqlalchemy.org/en/21/orm/extensions/asyncio.html Truy cập 22/10/2026.',
      '[4] Twilio. Messages resource. https://www.twilio.com/docs/messaging/api/message-resource Truy cập 22/10/2026.',
      '[5] Python. smtplib. https://docs.python.org/3.12/library/smtplib.html Truy cập 22/10/2026.',
      '[6] OWASP. WebSocket Security, Password Storage and Session Management Cheat Sheets. https://cheatsheetseries.owasp.org/ Truy cập 22/10/2026.',
      '[7] Tài liệu học phần Lập trình mạng 2026–2027. Instruction.md, Submission.md và đặc tả giảng viên được nhóm cung cấp. Yêu cầu dự án: https://chatgpt.com/share/6ad98a6a-9cb8-83ec-9c33-f73b27861086 .']:
        p(ref)
    h('18 Phụ lục bàn giao')
    p('Source chứa frontend, backend, migration, seed, script cài/chạy/test, công cụ thực nghiệm, tài liệu và evidence. File .env, mật khẩu, token, private key TLS, database dump và ảnh khách thật không nằm trong gói source. Đóng góp cá nhân dưới đây cần từng thành viên xác nhận bằng công việc và minh chứng thực tế; không coi đề xuất phân công là thành tích đã thực hiện.')
    table(doc,['Thành viên','Phần thực tế và minh chứng xác nhận'],[(m['name'],'Chưa xác nhận bởi thành viên') for m in team['members']],[2.3,4.3])
    p('Nhóm thực hiện Compilatio và nộp một báo cáo .docx theo quy định. Hạn trong tài liệu học phần là 23:59 ngày 31/10/2026. Không có kết quả Compilatio hoặc xác nhận đóng góp được tự điền trong báo cáo này.')
    folder=ROOT/'report';folder.mkdir(exist_ok=True)
    target=folder/'Nhom17_RealtimeOrders_Report.docx';doc.save(target)
    print('Created report:',target)

if __name__=='__main__':main()
