type Log = Record<string, any>;
const entities: Record<string,string> = {customer_groups:"nhóm khách hàng",categories:"danh mục",units:"đơn vị",delivery_zones:"khu vực giao",delivery_policies:"chính sách giao",pickup_slots:"điểm giao tập trung",moderation_rules:"quy tắc nội dung"};
export function activityLabel(r: Log): string {
 const a=r.after_data ?? {},b=r.before_data ?? {};
 if(r.action==="user.update") {
  if(a.status && a.status!==b.status) return ({DELETED:"Xóa mềm tài khoản",LOCKED:"Khóa tài khoản",ACTIVE:"Mở khóa tài khoản"} as Record<string,string>)[a.status] ?? "Cập nhật tài khoản";
  return a.group_id && a.group_id!==b.group_id ? "Đổi nhóm khách hàng" : "Cập nhật tài khoản";
 }
 if(r.action==="product.update") return a.deleted_at ? "Xóa mềm sản phẩm" : !r.before_data ? "Thêm sản phẩm" : "Cập nhật sản phẩm";
 if(r.action==="menu.save") return a.status==="CLOSED" ? "Đóng đợt bán" : a.status==="OPEN" && b.status!=="OPEN" ? "Mở đợt bán" : !r.before_data ? "Tạo đợt bán nháp" : "Cập nhật đợt bán";
 const labels:Record<string,string>={"menu.item.remove":"Ngừng bán sản phẩm trong đợt","inventory.adjust":"Điều chỉnh tồn kho","order.approve":"Duyệt đơn hàng","order.reject":"Từ chối đơn hàng","order.cancel":"Hủy đơn hàng","order.request-cancel":"Gửi yêu cầu hủy đơn","order.decide-cancel":"Xử lý yêu cầu hủy đơn","order.transition":"Chuyển trạng thái đơn","warehouse.update":"Cập nhật vị trí kho","verified_location.update":"Cập nhật địa chỉ đã xác nhận"};
 if(labels[r.action]) return labels[r.action];
 if(r.action?.endsWith(".update") && entities[r.entity_type]) return (r.before_data ? "Cập nhật " : "Thêm ")+entities[r.entity_type];
 const stock:Record<string,string>={APPROVE:"Trừ kho khi duyệt đơn",CANCEL_RESTORE:"Hoàn kho khi hủy đơn",MANUAL_ADJUST:"Điều chỉnh tồn kho",INITIAL:"Nhập tồn ban đầu"};
 if(stock[r.kind])return stock[r.kind];
 if(r.field_name)return "Phát hiện nội dung không phù hợp";
 return r.action ? "Thao tác khác ("+r.action+")" : r.kind ? "Biến động kho ("+r.kind+")" : "Cập nhật dữ liệu";
}
export const activityFields:Record<string,string>={status:"Trạng thái",group_id:"Nhóm khách hàng",display_name:"Tên hiển thị",name:"Tên",active:"Sử dụng",quantity:"Tồn kho",delta:"Lượng điều chỉnh",reason:"Lý do",default_cost_price:"Giá nhập mẫu",default_sale_price:"Giá bán mẫu",cost_price:"Giá nhập",quantity_step:"Bước số lượng",sale_date:"Ngày bán",opens_at:"Bắt đầu bán",closes_at:"Kết thúc bán",allowed_group_ids:"Nhóm được phép mua",audience_mode:"Cách chọn nhóm",address:"Địa chỉ",latitude:"Vĩ độ",longitude:"Kinh độ",deleted_at:"Xóa lúc",shipping_fee:"Phí cơ bản",per_km_fee:"Phí mỗi km",extra_km_fee:"Phí km vượt",included_km:"Mốc km",max_distance_km:"Khoảng cách tối đa",minimum_subtotal:"Tiền hàng tối thiểu",code:"Mã",description:"Mô tả",label:"Nhãn"};
export function changedFields(r:Log):string[]{
 const a=r.after_data ?? {},b=r.before_data ?? {};
 return Object.keys(activityFields).filter(k=>Object.prototype.hasOwnProperty.call(a,k)&&JSON.stringify(a[k])!==JSON.stringify(b[k]));
}
