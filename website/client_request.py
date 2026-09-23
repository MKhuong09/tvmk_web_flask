from flask import Blueprint, current_app, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from datetime import datetime
from .models import Registration, Notification
from . import db  # Import đối tượng db Firestore đã khởi tạo ở __init__.py
from website.models import Registration, Notification, User, db
from mailAgent.mailbox import send_email

client_request = Blueprint('client_request', __name__)

# Hiển thị giao diện trang form gửi phiếu yêu cầu
@client_request.route('/request-shift-change/<string:id>', methods=['GET'])
@login_required
def request_shift_change_form(id):
    # Truy vấn Firestore để lấy thông tin Registration
    reg_ref = db.collection('registrations').document(id)
    reg_doc = reg_ref.get()
    
    if not reg_doc.exists:
        flash('Không tìm thấy lịch trực này.', 'danger')
        return redirect(url_for('client_views.client_detailshift'))
        
    reg = Registration(reg_doc.id, reg_doc.to_dict())
    
    # Kiểm tra bảo mật 
    if reg.user_id != current_user.id:
        flash('Bạn không có quyền thao tác trên lịch này.', 'danger')
        return redirect(url_for('client_views.client_detailshift'))
        
    return render_template('clients/client_request_form.html', reg=reg)


# Xử lý logic khi người dùng điền xong và bấm "Gửi phiếu yêu cầu"
@client_request.route('/submit-shift-adjustment/<string:id>', methods=['POST'])
@login_required
def submit_shift_adjustment(id):
    reg_ref = db.collection('registrations').document(id)
    reg_doc = reg_ref.get()
    
    if not reg_doc.exists:
        flash('Không tìm thấy lịch trực này.', 'danger')
        return redirect(url_for('client_views.client_detailshift'))
        
    reg = Registration(reg_doc.id, reg_doc.to_dict())
    
    if reg.user_id != current_user.id:
        flash('Bạn không có quyền thao tác trên lịch này.', 'danger')
        return redirect(url_for('client_views.client_detailshift'))
        
    reason = request.form.get('reason')
    new_session = request.form.get('new_session')
    
    if not reason or not reason.strip():
        flash('Vui lòng nhập lý do muốn thay đổi lịch.', 'warning')
        return redirect(url_for('client_request.request_shift_change_form', id=reg.id))
        
    # Tạo dữ liệu thông báo gửi cho Admin lưu vào Firestore
    notif_data = {
        'user_id': current_user.id,
        'registration_id': reg.id,
        'title': "Yêu cầu thay đổi lịch trực",
        'message': f"Học viên {getattr(current_user, 'user_name', 'Học viên')} gửi yêu cầu đổi lịch (Tuần {getattr(reg, 'week_number', '')}). Đổi sang: {new_session}. Lý do: '{reason}'.",
        'status': 'pending',
        'is_read': False,
        'created_at': datetime.utcnow()
    }
    
    # Thêm document vào collection 'notifications' trên Firestore
    db.collection('notifications').add(notif_data)
    # Tạo thông báo gửi cho Admin
    new_request_notif = Notification(
        user_id=current_user.id,
        title="Yêu cầu thay đổi lịch trực",
        message=f"Học viên {current_user.user_name} gửi yêu cầu đổi lịch (Tuần {reg.week_number}). Đổi sang: {new_session}. Lý do: '{reason}'.",
        status='pending'
    )
    
    db.session.add(new_request_notif)
    db.session.commit()

    admin_emails = [
        user.email for user in User.query.filter(User.role_id.in_([1, 3])).all()
        if user.email
    ]
    send_email(
        current_app,
        admin_emails,
        f'Yêu cầu thay đổi lịch từ {current_user.user_name}',
        new_request_notif.message,
    )
    
    flash('Gửi phiếu yêu cầu thay đổi lịch thành công!', 'success')
    return redirect(url_for('client_views.client_detailshift'))