from datetime import datetime
from typing import cast,Any

from firebase_admin import firestore
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from google.cloud.firestore_v1.client import Client as FirestoreClient

from .models import Registration


client_request = Blueprint("client_request", __name__)


def get_db() -> FirestoreClient:
    return cast(FirestoreClient, firestore.client())


@client_request.route(
    '/request-shift-change/<string:id>',
    methods=['GET'],
)
@login_required
def request_shift_change_form(id: str):
    db = get_db()

    reg_ref = db.collection('registrations').document(id)
    reg_doc = cast(Any, reg_ref.get())

    if not reg_doc.exists:
        flash('Không tìm thấy lịch trực này.', 'danger')
        return redirect(url_for('client_views.client_detailshift'))

    reg = Registration(reg_doc.id, reg_doc.to_dict() or {})

    if reg.user_id != current_user.id:
        flash('Bạn không có quyền thao tác trên lịch này.', 'danger')
        return redirect(url_for('client_views.client_detailshift'))

    return render_template('clients/client_request_form.html', reg=reg)
@client_request.route(
    "/submit-shift-adjustment/<string:id>",
    methods=["POST"],
)
@client_request.route(
    '/submit-shift-adjustment/<string:id>',
    methods=['POST'],
)
@login_required
def submit_shift_adjustment(id: str):
    db = get_db()

    reg_ref = db.collection('registrations').document(id)
    reg_doc = cast(Any, reg_ref.get())

    if not reg_doc.exists:
        flash('Không tìm thấy lịch trực này.', 'danger')
        return redirect(url_for('client_views.client_detailshift'))

    reg = Registration(reg_doc.id, reg_doc.to_dict() or {})

    if reg.user_id != current_user.id:
        flash('Bạn không có quyền thao tác trên lịch này.', 'danger')
        return redirect(url_for('client_views.client_detailshift'))

    reason = request.form.get('reason')
    new_session = request.form.get('new_session')

    if not reason or not reason.strip():
        flash('Vui lòng nhập lý do muốn thay đổi lịch.', 'warning')
        return redirect(
            url_for('client_request.request_shift_change_form', id=reg.id)
        )

    notif_data = {
        'user_id': current_user.id,
        'registration_id': reg.id,
        'title': 'Yêu cầu thay đổi lịch trực',
        'message': (
            f"Học viên {getattr(current_user, 'user_name', 'Học viên')} "
            f"gửi yêu cầu đổi lịch "
            f"(Tuần {getattr(reg, 'week_number', '')}). "
            f"Đổi sang: {new_session}. Lý do: '{reason}'."
        ),
        'status': 'pending',
        'is_read': False,
        'created_at': datetime.utcnow(),
    }

    db.collection('notifications').add(notif_data)

    flash('Gửi phiếu yêu cầu thay đổi lịch thành công!', 'success')
    return redirect(url_for('client_views.client_detailshift'))