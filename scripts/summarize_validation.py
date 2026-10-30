"""Summarize completed runs; no expected values substituted for missing evidence."""
import json
import statistics
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]

def main():
    suites=list(ET.parse(ROOT/'evidence/integration.xml').getroot().iter('testsuite'))
    tests=sum(int(x.get('tests',0)) for x in suites);failed=sum(int(x.get('failures',0))+int(x.get('errors',0)) for x in suites)
    browser=json.loads((ROOT/'evidence/browser-results.json').read_text(encoding='utf-8'))['stats']
    loads=[json.loads(p.read_text(encoding='utf-8'))|{'file':p.name} for p in (ROOT/'evidence/load').glob('*.json')]
    comparisons=[json.loads(p.read_text(encoding='utf-8'))|{'file':p.name} for p in (ROOT/'evidence/comparison').glob('*.json')]
    comp=next(d for d in reversed(comparisons) if d.get('validTiming'))
    w=[r for r in comp['runs'] if r['mode']=='wss'];b=[r for r in comp['runs'] if r['mode']=='polling']
    reduction=100*(1-statistics.mean(r['bytes'] for r in w)/statistics.mean(r['bytes'] for r in b))
    lines=['# Kết quả kiểm chứng RealtimeOrders','',
        'Ngày 22/10/2026. Tất cả số liệu dưới đây thuộc dự án này, không dùng kết quả BoardLAN/game.',
        '',f'- Python: **{tests} ca, {failed} lỗi**; nguồn `evidence/integration.xml`.',
        f'- Browser Edge: **{browser["expected"]} đạt, {browser["unexpected"]} lỗi, {browser["skipped"]} bỏ qua**; nguồn `evidence/browser-results.json`.',
        '- Build Next.js/TypeScript chạy thành công. Cookie Secure, HTTPS/WSS tự ký trong môi trường thử.',
        '- Backup/restore vào database mới: `evidence/restore-check.json`; dữ liệu nghiệp vụ và hash bản sao ảnh được đối chiếu.',
        '- Backend dừng → commit event pending → khởi động → publish/replay WSS và order hash giữ nguyên: `evidence/restart-probe.json`.',
        '', '## Tải kết nối','',
        '| Run | Khách / socket cuối | Giây đo | GET/s thực | API p95 ms | Event p95 ms | Lỗi |',
        '|---|---:|---:|---:|---:|---:|---:|']
    for d in sorted(loads,key=lambda x:x['timestampUtc']):
        lines.append(f'| `{d["file"]}` | {d["requestedDistinctCustomers"]} / {d["activeAtEnd"]} | {d["measurementSeconds"]} | {d["successfulCatalogRequests"]/d["measurementSeconds"]:.2f} | {d["catalogP95Ms"]} | {d["eventP95Ms"]} | {len(d["errors"])} |')
    final=max((d for d in loads if d.get('variant')),key=lambda x:x['requestedDistinctCustomers'])
    lines+=['','Tất cả các lượt yêu cầu 10 GET/s toàn hệ thống; không phải 10 GET/s mỗi khách. '
        'Generator, proxy, FastAPI và MySQL cùng máy Windows/loopback. Workload đặt/duyệt đơn là **0/s**, '
        'do đó không coi đây là chứng minh 2.000 người đang mua hàng tích cực.',
        '',f'Lượt theo lô `{final["file"]}` có {final.get("recoveredConnections",0)} socket phục hồi sau khi ngắt 10% '
        f'tại giây 20 và chờ 5 giây. p95 nối lại đến SYNC_END {final.get("recoveryP95Ms")} ms, gồm chờ semaphore '
        'của generator, không gồm 5 giây cố ý ngắt. Dùng snapshot, không phải replay incremental.',
        '', '**Giới hạn:** Giữ được 2.000 kết nối, nhưng chưa đạt đồng thời tốc độ đọc yêu cầu và mục tiêu '
        'p95 event 500 ms ở mức tải đó. Không xóa các lượt chưa đạt. Các lượt đầu khác phiên bản/working set '
        '(100/500 có các đợt TEST còn mở; sau đó đã đóng), không dùng bảng này như thí nghiệm nhân quả có '
        'kiểm soát cho mọi tối ưu. Lượt cuối còn có thêm reconnect. Raw resource samples của lượt đầu có '
        'wrapper process; không cộng mọi dòng rồi gọi là RAM/CPU server.',
        '', '## WSS so với polling','',
        f'Nguồn `{comp["file"]}` và CSV observations cùng tên. {comp["clients"]} khách khác nhau, hai nhóm giá, '
        f'{comp["benchmarkOfferCount"]} offer thử, 2 thay đổi/s. Warmup {comp["warmupSeconds"]}s, đo '
        f'{comp["measurementSeconds"]}s, {comp["repeats"]} lần/mode, đảo thứ tự mode giữa các lần.',
        '', '| Mode | Lần | GET | MiB JSON | Quan sát mới | p50 ms | p95 ms | Hội tụ sau drain 2,5s | Lỗi |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in comp['runs']:
        lines.append(f'| {r["mode"]} | {r["repeat"]} | {r["requests"]} | {r["bytes"]/1048576:.2f} | {r["observedChanges"]} | {r["p50Ms"]} | {r["p95Ms"]} | {r["convergedClientsAfterDrain"]}/{r["clients"]} | {r["errors"]} |')
    lines+=['',f'Payload JSON trung bình WSS thấp hơn {reduction:.1f}% trong workload này. '
        'Không gồm header/TLS/packet capture/bootstrap. Không tự suy ra tiết kiệm đường truyền ở mọi workload. '
        'Observer ghi latency từ trước transaction producer đến khi parse phiên bản mới bằng cùng perf_counter; '
        'loại phiên bản sinh trong warmup. Không phải thời gian pixel xuất hiện trên browser.',
        '', 'Polling có thể trễ và chưa hội tụ trong 2,5s drain do hàng đợi; không diễn giải thành mất gói TCP '
        'hay dữ liệu vĩnh viễn sai. Các lượt thăm dò `validTiming=false` bị loại khỏi so sánh latency cuối vì '
        'công cụ cũ tính cả version từ warmup; raw vẫn được giữ và có exclusionReason.',
        '', '## Phạm vi các kiểm tra','',
        'Các ca Python bao phủ các phần chính TC01–TC28: OTP sai/hết hạn/reuse; quyền/CSRF/Origin; email demo; '
        'địa chỉ đồng thời; giá nhóm; Decimal/số lỗi; giao tập trung/mức tối thiểu; pending/dedup; tranh kho; '
        'duyệt nguyên đơn; hủy/hoàn; version; báo cáo; chat/ảnh/kiểm duyệt; quote hết hạn và snapshot giá/phí/tên; '
        'WSS snapshot/replay/frame; idle monitor; queue giới hạn; notification job và thứ tự head lock.',
        '', 'Đây **không phải** tuyên bố mọi biến thể trong từng TC hoặc ma trận E1–E3 đều đã chạy. Chưa có '
        'ma trận 24 lượt 60s ở mọi mức tải, fault injection ở mọi điểm commit, thử chậm bằng mạng nhiều máy, '
        'đo trên hai thiết bị LAN, thử người dùng, SMS/email nhà cung cấp và kiểm tra Compilatio.',
        '', 'Các phép tải chính được chạy trước một số chỉnh sửa cuối về snapshot thông tin theo dõi và báo giá; '
        'luồng nghiệp vụ/giao thức cuối được kiểm tra lại bằng Python/browser. Không coi số liệu này là SLA '
        'của mọi bản build hoặc môi trường triển khai.',
        '', '## Trước khi nộp','',
        'Nhóm xác nhận đóng góp cá nhân, hiểu code, thử hai thiết bị, điền dữ liệu bán hàng thực tế, '
        'kiểm tra Compilatio và tự nộp theo hướng dẫn. Adapter có mã chưa đồng nghĩa đã gửi SMS/email thật.']
    (ROOT/'evidence/validation-summary.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    result={'pythonTests':tests,'pythonFailures':failed,'browser':browser,'loadRuns':len(loads),'comparisonSource':comp['file'],
        'comparisonPayloadReductionPercent':round(reduction,2),'backupRestoreEvidence':'restore-check.json',
        'restartEvidence':'restart-probe.json','realSmsVerified':False,'twoDeviceLanVerified':False,'compilatioVerified':False}
    (ROOT/'evidence/validation-summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
