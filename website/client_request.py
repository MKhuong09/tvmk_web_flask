from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from website.models import Registration, Notification, db

client_request = Blueprint('client_request', __name__)

# Route GET: Hiển thị giao diện trang form gửi phiếu yêu cầu
@client_request.route('/request-shift-change/<int:id>', methods=['GET'])
@login_required
def request_shift_change_form(id):
    reg = Registration.query.get_or_404(id)
    
    # Kiểm tra bảo mật
    if reg.user_id != current_user.id:
        flash('Bạn không có quyền thao tác trên lịch này.', 'danger')
        return redirect(url_for('client_views.client_detailshift'))
        
    # Trả về trang file HTML client_request_form.html nằm trong thư mục clients của em
    return render_template('clients/client_request_form.html', reg=reg)


# Route POST: Xử lý logic khi người dùng điền xong và bấm "Gửi phiếu yêu cầu"
@client_request.route('/submit-shift-adjustment/<int:id>', methods=['POST'])
@login_required
def submit_shift_adjustment(id):
    reg = Registration.query.get_or_404(id)
    
    if reg.user_id != current_user.id:
        flash('Bạn không có quyền thao tác trên lịch này.', 'danger')
        return redirect(url_for('client_views.client_detailshift'))
        
    reason = request.form.get('reason')
    new_session = request.form.get('new_session') # Lấy thêm giá trị ca mới nếu form của em có ô select
    
    if not reason or not reason.strip():
        flash('Vui lòng nhập lý do muốn thay đổi lịch.', 'warning')
        return redirect(url_for('client_request.request_shift_change_form', id=reg.id))
        
    # Tạo thông báo gửi cho Admin
    new_request_notif = Notification(
        user_id=current_user.id,
        registration_id=reg.id,
        title="Yêu cầu thay đổi lịch trực",
        message=f"Học viên {current_user.user_name} gửi yêu cầu đổi lịch (Tuần {reg.week_number}). Đổi sang: {new_session}. Lý do: '{reason}'.",
        status='pending'
    )
    
    db.session.add(new_request_notif)
    db.session.commit()
    
    flash('Gửi phiếu yêu cầu thay đổi lịch thành công!', 'success')
    return redirect(url_for('client_views.client_detailshift'))