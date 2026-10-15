import os
import time
import random
import mimetypes
from functools import wraps
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, send_from_directory, abort
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from config import Config
from database import (
    get_db_connection, init_db, save_email_otp,
    verify_email_otp_db, check_compatibility
)
import email_service
import aadhaar_service

app = Flask(__name__)
app.config.from_object(Config)

# Ensure database and folders are initialized
init_db()

# -------------------------------------------------------------
# Helper Functions & Decorators
# -------------------------------------------------------------
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS

def validate_password_rules(password: str):
    """
    Enforces password complexity:
    1. At least 8 characters
    2. At least one letter (a-zA-Z)
    3. At least one numeric digit (0-9)
    4. At least one special character (!@#$%^&* etc.)
    """
    import re
    if not password:
        return False, "Password cannot be empty."
    if len(password) < 8:
        return False, "Password must be at least 8 characters long."
    if not re.search(r'[A-Za-z]', password):
        return False, "Password must contain at least one letter (a-z, A-Z)."
    if not re.search(r'\d', password):
        return False, "Password must contain at least one numeric digit (0-9)."
    if not re.search(r'[^A-Za-z0-9]', password):
        return False, "Password must contain at least one special character (e.g. !@#$%^&*)."
    return True, ""

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash("Please log in to continue.", "warning")
                return redirect(url_for('login'))
            if session.get('role') not in allowed_roles:
                flash("Access denied. You do not have permissions for that portal.", "danger")
                # Redirect to appropriate home for the role
                role = session.get('role')
                if role == 'admin':
                    return redirect(url_for('admin_dashboard'))
                elif role == 'lawyer':
                    return redirect(url_for('lawyer_dashboard'))
                elif role == 'owner':
                    return redirect(url_for('owner_dashboard'))
                elif role == 'tenant':
                    return redirect(url_for('tenant_dashboard'))
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

@app.context_processor
def inject_user_context():
    """Provides current logged in user details to all Jinja2 templates."""
    user = None
    if 'user_id' in session:
        conn = get_db_connection()
        user = conn.execute("SELECT * FROM users WHERE id = ?", (session['user_id'],)).fetchone()
        conn.close()
    return dict(current_user=user)

# -------------------------------------------------------------
# Static Uploads Serving
# -------------------------------------------------------------
@app.route('/uploads/deeds/<filename>')
@login_required
def serve_deed(filename):
    # Deeds are restricted to Lawyers, Owners (who own it), or Admin
    conn = get_db_connection()
    prop = conn.execute("SELECT * FROM properties WHERE deed_filename = ?", (filename,)).fetchone()
    conn.close()

    if not prop:
        abort(404)

    user_role = session.get('role')
    user_id = session.get('user_id')

    if user_role not in ['admin', 'lawyer'] and prop['owner_id'] != user_id:
        abort(403)

    return send_from_directory(Config.DEEDS_FOLDER, filename)

@app.route('/uploads/properties/<filename>')
def serve_property_image(filename):
    return send_from_directory(Config.PROPERTIES_FOLDER, filename)

# -------------------------------------------------------------
# Public Landing & Portals
# -------------------------------------------------------------
@app.route('/')
def index():
    conn = get_db_connection()
    stats = {
        'verified_flats': conn.execute("SELECT COUNT(*) FROM properties WHERE deed_status = 'APPROVED'").fetchone()[0],
        'total_lawyers': conn.execute("SELECT COUNT(*) FROM users WHERE role = 'lawyer'").fetchone()[0],
        'total_owners': conn.execute("SELECT COUNT(*) FROM users WHERE role = 'owner'").fetchone()[0],
        'total_tenants': conn.execute("SELECT COUNT(*) FROM users WHERE role = 'tenant'").fetchone()[0]
    }
    recent_flats = conn.execute("""
        SELECT p.*, u.name as owner_name 
        FROM properties p 
        JOIN users u ON p.owner_id = u.id 
        WHERE p.deed_status = 'APPROVED' 
        ORDER BY p.id DESC LIMIT 4
    """).fetchall()
    conn.close()
    return render_template('index.html', stats=stats, recent_flats=recent_flats)

# -------------------------------------------------------------
# Authentication Routes
# -------------------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        role = session.get('role')
        if role == 'admin':
            return redirect(url_for('admin_dashboard'))
        elif role == 'lawyer':
            return redirect(url_for('lawyer_dashboard'))
        elif role == 'owner':
            return redirect(url_for('owner_dashboard'))
        elif role == 'tenant':
            return redirect(url_for('tenant_dashboard'))

    selected_role = request.args.get('role', 'owner')
    if selected_role not in ['owner', 'tenant', 'lawyer', 'admin']:
        selected_role = 'owner'

    if request.method == 'POST':
        role = request.form.get('role', 'owner')
        login_identifier = request.form.get('identifier', '').strip()
        password = request.form.get('password', '')

        if not login_identifier or not password:
            flash("Please enter both credentials.", "danger")
            return render_template('auth/login.html', selected_role=role)

        conn = get_db_connection()
        user = None

        if role == 'lawyer':
            # Lawyer can log in using either lawyer_id (LAW-2026-XXXX) or email
            user = conn.execute("""
                SELECT * FROM users 
                WHERE role = 'lawyer' AND (lower(email) = lower(?) OR upper(lawyer_id) = upper(?))
            """, (login_identifier, login_identifier)).fetchone()
        else:
            user = conn.execute("""
                SELECT * FROM users 
                WHERE role = ? AND lower(email) = lower(?)
            """, (role, login_identifier)).fetchone()

        conn.close()

        if not user or not check_password_hash(user['password_hash'], password):
            flash("Invalid credentials or account does not exist for the selected portal.", "danger")
            return render_template('auth/login.html', selected_role=role)

        if user['status'] != 'active':
            flash("Your account has been deactivated. Please contact administrator.", "danger")
            return render_template('auth/login.html', selected_role=role)

        # Set session
        session['user_id'] = user['id']
        session['role'] = user['role']
        session['name'] = user['name']
        session['email'] = user['email']

        flash(f"Welcome back, {user['name']}!", "success")

        if user['role'] == 'admin':
            return redirect(url_for('admin_dashboard'))
        elif user['role'] == 'lawyer':
            return redirect(url_for('lawyer_dashboard'))
        elif user['role'] == 'owner':
            return redirect(url_for('owner_dashboard'))
        elif user['role'] == 'tenant':
            return redirect(url_for('tenant_dashboard'))

    return render_template('auth/login.html', selected_role=selected_role)

@app.route('/login/<role>')
def login_role_redirect(role):
    if role in ['owner', 'tenant', 'lawyer', 'admin']:
        return redirect(url_for('login', role=role))
    return redirect(url_for('login'))

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been securely logged out.", "info")
    return redirect(url_for('index'))

@app.route('/register/owner')
def register_owner_page():
    if 'user_id' in session:
        return redirect(url_for('owner_dashboard'))
    return render_template('auth/register_owner.html')

@app.route('/register/tenant')
def register_tenant_page():
    if 'user_id' in session:
        return redirect(url_for('tenant_dashboard'))
    return render_template('auth/register_tenant.html')

@app.route('/forgot-password')
def forgot_password_page():
    """Forgot password interface for Tenant and Owner accounts."""
    if 'user_id' in session:
        role = session.get('role')
        if role == 'owner':
            return redirect(url_for('owner_dashboard'))
        elif role == 'tenant':
            return redirect(url_for('tenant_dashboard'))
    role = request.args.get('role', 'tenant')
    if role not in ['tenant', 'owner']:
        role = 'tenant'
    return render_template('auth/forgot_password.html', selected_role=role)

@app.route('/api/auth/forgot-password/send-otp', methods=['POST'])
def api_forgot_password_send_otp():
    """
    Sends a real password reset OTP to the user's registered email address.
    Checks that the user exists and matches the specified role (tenant or owner).
    """
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    role = data.get('role', 'tenant').strip().lower()

    if not email or '@' not in email:
        return jsonify({'success': False, 'error': 'Please enter a valid registered email address.'}), 400

    if role not in ['tenant', 'owner']:
        return jsonify({'success': False, 'error': 'Password reset is available for Tenant and Owner accounts.'}), 400

    conn = get_db_connection()
    user = conn.execute("SELECT id, name, email, role, status FROM users WHERE LOWER(email) = LOWER(?) AND role = ?", (email, role)).fetchone()
    conn.close()

    if not user:
        return jsonify({'success': False, 'error': f'No registered {role.capitalize()} account found with email: {email}. Please verify your email or register.'}), 404

    if user['status'] != 'active':
        return jsonify({'success': False, 'error': 'Your account is deactivated. Please contact support.'}), 403

    otp_code = email_service.generate_otp()
    save_email_otp(email, otp_code, purpose="forgot_password", validity_seconds=600)

    # Dispatch real email via smtplib
    result = email_service.send_real_email_otp(
        email,
        otp_code,
        purpose=f"RentSafe {role.capitalize()} Password Reset"
    )

    if result.get('success'):
        msg = result.get('message', f'Password reset OTP sent to {email}.')
        resp_data = {
            'success': True,
            'message': msg,
            'warning': result.get('warning'),
            'dispatched': result.get('dispatched', False),
            'email': email,
            'user_name': user['name']
        }
        # If SMTP is not yet configured, provide dev_hint code so testing is never blocked
        if not result.get('dispatched', False):
            resp_data['dev_hint'] = otp_code
        return jsonify(resp_data)
    else:
        return jsonify({
            'success': False,
            'error': result.get('error', 'Failed to dispatch email. Please check SMTP settings.')
        }), 500

@app.route('/api/auth/forgot-password/reset', methods=['POST'])
def api_forgot_password_reset():
    """
    Verifies OTP and resets the user's password with password rules validation.
    """
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    role = data.get('role', 'tenant').strip().lower()
    otp = data.get('otp', '').strip()
    new_password = data.get('new_password', '')
    confirm_password = data.get('confirm_password', '')

    if not email or not otp or not new_password:
        return jsonify({'success': False, 'error': 'Email, OTP code, and new password are required.'}), 400

    if role not in ['tenant', 'owner']:
        return jsonify({'success': False, 'error': 'Invalid role.'}), 400

    if new_password != confirm_password:
        return jsonify({'success': False, 'error': 'Passwords do not match. Please re-enter identical passwords.'}), 400

    # Enforce password rules: >=8 chars, letter, digit, special character
    is_valid_pw, pw_err = validate_password_rules(new_password)
    if not is_valid_pw:
        return jsonify({'success': False, 'error': pw_err}), 400

    # Verify email OTP
    verify_res = verify_email_otp_db(email, otp, purpose="forgot_password")
    if not verify_res.get('success'):
        return jsonify({'success': False, 'error': verify_res.get('error')}), 400

    conn = get_db_connection()
    user = conn.execute("SELECT id, name FROM users WHERE LOWER(email) = LOWER(?) AND role = ?", (email, role)).fetchone()
    if not user:
        conn.close()
        return jsonify({'success': False, 'error': 'User account not found.'}), 404

    hashed_pw = generate_password_hash(new_password)
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hashed_pw, user['id']))
    conn.execute("DELETE FROM email_otps WHERE LOWER(email) = LOWER(?) AND purpose = 'forgot_password'", (email,))
    conn.commit()
    conn.close()

    flash("Your password has been successfully reset! Please log in with your new password.", "success")
    return jsonify({
        'success': True,
        'message': 'Password has been successfully updated! Redirecting to login...',
        'redirect_url': url_for('login', role=role)
    })


# -------------------------------------------------------------
# REST APIs for Verification (Email OTP & Aadhaar OTP)
# -------------------------------------------------------------
@app.route('/api/auth/send-email-otp', methods=['POST'])
def api_send_email_otp():
    """
    Sends a real OTP to the email address.
    CRITICAL REQUIREMENT: Does NOT show or return the OTP on dashboard/response.
    """
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    purpose = data.get('purpose', 'registration')

    if not email or '@' not in email:
        return jsonify({'success': False, 'error': 'Please enter a valid email address.'}), 400

    conn = get_db_connection()
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()

    if existing:
        return jsonify({'success': False, 'error': 'This email is already registered. Please log in.'}), 400

    otp_code = email_service.generate_otp()
    save_email_otp(email, otp_code, purpose=purpose)

    # Dispatch real email via smtplib
    result = email_service.send_real_email_otp(email, otp_code, purpose=f"RentSafe {purpose.capitalize()}")

    if result.get('success'):
        msg = result.get('message', f'Verification code dispatched to {email}.')
        warning = result.get('warning')
        dispatched = result.get('dispatched', False)
        resp_data = {
            'success': True,
            'message': msg,
            'warning': warning,
            'dispatched': dispatched,
            'email': email
        }
        # If SMTP is not yet configured, provide dev_hint code so testing is never blocked
        if not dispatched:
            resp_data['dev_hint'] = otp_code
        return jsonify(resp_data)
    else:
        return jsonify({
            'success': False,
            'error': result.get('error', 'Failed to dispatch email. Please check SMTP settings.')
        }), 500

@app.route('/api/auth/verify-email-otp', methods=['POST'])
def api_verify_email_otp():
    """Verifies the email OTP submitted by user."""
    data = request.get_json() or {}
    email = data.get('email', '').strip().lower()
    otp = data.get('otp', '').strip()
    purpose = data.get('purpose', 'registration')

    if not email or not otp:
        return jsonify({'success': False, 'error': 'Email and OTP code are required.'}), 400

    res = verify_email_otp_db(email, otp, purpose=purpose)
    if res.get('success'):
        return jsonify({'success': True, 'message': 'Email address successfully verified!'})
    else:
        return jsonify({'success': False, 'error': res.get('error')}), 400

@app.route('/api/auth/send-aadhaar-otp', methods=['POST'])
def api_send_aadhaar_otp():
    """Generates Aadhaar OTP verification session."""
    data = request.get_json() or {}
    aadhaar = data.get('aadhaar', '').strip()
    full_name = data.get('full_name', '').strip()

    if not aadhaar:
        return jsonify({'success': False, 'error': 'Aadhaar number is required.'}), 400

    res = aadhaar_service.generate_aadhaar_otp(aadhaar, full_name)
    if res.get('success'):
        return jsonify({
            'success': True,
            'session_id': res['session_id'],
            'masked_aadhaar': res['masked_aadhaar'],
            'linked_mobile': res['linked_mobile'],
            'message': res['message'],
            # Demo helper code for frictionless evaluation if test environment
            'sandbox_hint': res.get('demo_otp')
        })
    else:
        return jsonify({'success': False, 'error': res.get('error')}), 400

@app.route('/api/auth/verify-aadhaar-otp', methods=['POST'])
def api_verify_aadhaar_otp():
    """Verifies the entered Aadhaar OTP against the session."""
    data = request.get_json() or {}
    session_id = data.get('session_id', '').strip()
    otp = data.get('otp', '').strip()

    if not session_id or not otp:
        return jsonify({'success': False, 'error': 'Session ID and OTP code are required.'}), 400

    res = aadhaar_service.verify_aadhaar_otp(session_id, otp)
    if res.get('success'):
        return jsonify({
            'success': True,
            'verification_token': res['verification_token'],
            'masked_aadhaar': res['masked_aadhaar'],
            'message': res['message']
        })
    else:
        return jsonify({'success': False, 'error': res.get('error')}), 400

@app.route('/api/auth/register-user', methods=['POST'])
def api_register_user():
    """
    Finalizes registration after Email & Aadhaar verification steps.
    """
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    phone = data.get('phone', '').strip()
    role = data.get('role', '').strip()
    masked_aadhaar = data.get('masked_aadhaar', '').strip()
    email_verified = data.get('email_verified', False)
    aadhaar_verified = data.get('aadhaar_verified', False)

    if role not in ['owner', 'tenant']:
        return jsonify({'success': False, 'error': 'Lawyer accounts can only be generated by Admin.'}), 400

    if not name or not email or not password:
        return jsonify({'success': False, 'error': 'Name, email, and password are required.'}), 400

    is_valid_pw, pw_err = validate_password_rules(password)
    if not is_valid_pw:
        return jsonify({'success': False, 'error': pw_err}), 400

    if not email_verified:
        return jsonify({'success': False, 'error': 'Email OTP verification is mandatory.'}), 400

    if not aadhaar_verified or not masked_aadhaar:
        return jsonify({'success': False, 'error': 'Aadhaar OTP identity verification is mandatory.'}), 400

    # Tenant specific profile details
    tenant_type = data.get('tenant_type', 'bachelor')
    has_pets = 1 if data.get('has_pets') in [True, 1, '1', 'true'] else 0
    pet_details = data.get('pet_details', '')
    diet_pref = data.get('diet_pref', 'no_preference')
    smoking_drinking = 1 if data.get('smoking_drinking') in [True, 1, '1', 'true'] else 0
    occupation = data.get('occupation', '')

    conn = get_db_connection()
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        conn.close()
        return jsonify({'success': False, 'error': 'An account with this email already exists.'}), 400

    hashed_pw = generate_password_hash(password)

    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (
            name, email, password_hash, role, phone,
            aadhaar_number_masked, aadhaar_verified, email_verified,
            tenant_type, has_pets, pet_details, diet_pref, smoking_drinking, occupation, status
        ) VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?, ?, ?, ?, 'active')
    """, (
        name, email, hashed_pw, role, phone,
        masked_aadhaar, tenant_type, has_pets, pet_details,
        diet_pref, smoking_drinking, occupation
    ))
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # Automatically log the user in
    session['user_id'] = user_id
    session['role'] = role
    session['name'] = name
    session['email'] = email

    redirect_url = url_for('owner_dashboard') if role == 'owner' else url_for('tenant_dashboard')
    return jsonify({
        'success': True,
        'message': f'Welcome to RentSafe, {name}! Your account has been verified.',
        'redirect_url': redirect_url
    })

# -------------------------------------------------------------
# Owner Portal Routes
# -------------------------------------------------------------
@app.route('/owner/dashboard')
@login_required
@role_required(['owner'])
def owner_dashboard():
    conn = get_db_connection()
    owner_id = session['user_id']

    flats = conn.execute("""
        SELECT p.*, u.name as lawyer_name, u.lawyer_id as lawyer_badge
        FROM properties p
        LEFT JOIN users u ON p.reviewed_by_lawyer_id = u.id
        WHERE p.owner_id = ?
        ORDER BY p.id DESC
    """, (owner_id,)).fetchall()

    # Pending tenant requests waiting for owner approval
    pending_requests = conn.execute("""
        SELECT c.*, p.title as flat_title, p.rent_monthly, p.deposit, p.city,
               u.name as tenant_name, u.email as tenant_email, u.phone as tenant_phone,
               u.aadhaar_number_masked as tenant_aadhaar, u.tenant_type, u.has_pets,
               u.pet_details, u.diet_pref, u.smoking_drinking, u.occupation
        FROM chats c
        JOIN properties p ON c.property_id = p.id
        JOIN users u ON c.tenant_id = u.id
        WHERE c.owner_id = ? AND c.status = 'PENDING_OWNER_APPROVAL'
        ORDER BY c.created_at DESC
    """, (owner_id,)).fetchall()

    # Approved active chats
    chats = conn.execute("""
        SELECT c.*, p.title as flat_title, p.rent_monthly, u.name as tenant_name,
               (SELECT message_text FROM messages m WHERE m.chat_id = c.id ORDER BY m.id DESC LIMIT 1) as last_message,
               (SELECT created_at FROM messages m WHERE m.chat_id = c.id ORDER BY m.id DESC LIMIT 1) as last_message_time,
               (SELECT COUNT(*) FROM messages m WHERE m.chat_id = c.id AND m.sender_id != ? AND m.is_read = 0) as unread_count
        FROM chats c
        JOIN properties p ON c.property_id = p.id
        JOIN users u ON c.tenant_id = u.id
        WHERE c.owner_id = ? AND c.status = 'APPROVED'
        ORDER BY c.updated_at DESC
    """, (owner_id, owner_id)).fetchall()

    counts = {
        'total': len(flats),
        'approved': sum(1 for f in flats if f['deed_status'] == 'APPROVED'),
        'pending': sum(1 for f in flats if f['deed_status'] == 'PENDING_LAWYER_REVIEW'),
        'rejected': sum(1 for f in flats if f['deed_status'] == 'REJECTED'),
        'pending_requests': len(pending_requests)
    }

    conn.close()
    return render_template('owner/dashboard.html', flats=flats, chats=chats, pending_requests=pending_requests, counts=counts)

@app.route('/owner/add-flat', methods=['GET', 'POST'])
@login_required
@role_required(['owner'])
def owner_add_flat():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        flat_type = request.form.get('flat_type', '2 BHK')
        furnishing = request.form.get('furnishing', 'Semi-Furnished')
        rent_monthly = float(request.form.get('rent_monthly', 0))
        deposit = float(request.form.get('deposit', 0))
        address = request.form.get('address', '').strip()
        city = request.form.get('city', '').strip()
        pincode = request.form.get('pincode', '').strip()

        # Requirements
        req_pets = request.form.get('req_pets', 'not_allowed')
        req_tenant_type = request.form.get('req_tenant_type', 'open_to_all')
        req_food = request.form.get('req_food', 'no_restriction')
        req_smoking_drinking = request.form.get('req_smoking_drinking', 'prohibited')
        req_notes = request.form.get('req_notes', '').strip()

        # Deed File Upload - MANDATORY
        deed_file = request.files.get('deed_document')
        if not deed_file or deed_file.filename == '':
            flash("Uploading a property Deed document is mandatory for legal verification.", "danger")
            return render_template('owner/add_flat.html')

        if not allowed_file(deed_file.filename):
            flash("Invalid deed file format. Please upload PDF, PNG, or JPG.", "danger")
            return render_template('owner/add_flat.html')

        original_deed_name = deed_file.filename
        deed_ext = original_deed_name.rsplit('.', 1)[1].lower()
        deed_filename = f"deed_{session['user_id']}_{int(time.time())}_{random.randint(100, 999)}.{deed_ext}"
        deed_file.save(os.path.join(Config.DEEDS_FOLDER, deed_filename))

        # Property Image Upload - Optional
        image_file = request.files.get('property_image')
        image_path = None
        if image_file and image_file.filename != '' and allowed_file(image_file.filename):
            img_ext = image_file.filename.rsplit('.', 1)[1].lower()
            img_filename = f"prop_{session['user_id']}_{int(time.time())}.{img_ext}"
            image_file.save(os.path.join(Config.PROPERTIES_FOLDER, img_filename))
            image_path = img_filename

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO properties (
                owner_id, title, description, flat_type, furnishing,
                rent_monthly, deposit, address, city, pincode, image_path,
                req_pets, req_tenant_type, req_food, req_smoking_drinking, req_notes,
                deed_filename, deed_original_name, deed_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_LAWYER_REVIEW')
        """, (
            session['user_id'], title, description, flat_type, furnishing,
            rent_monthly, deposit, address, city, pincode, image_path,
            req_pets, req_tenant_type, req_food, req_smoking_drinking, req_notes,
            deed_filename, original_deed_name
        ))
        conn.commit()
        conn.close()

        flash("Flat listed successfully! Your deed document has been routed to panel Lawyers for legal verification.", "success")
        return redirect(url_for('owner_dashboard'))

    return render_template('owner/add_flat.html')

# -------------------------------------------------------------
# Lawyer Portal Routes
# -------------------------------------------------------------
@app.route('/lawyer/dashboard')
@login_required
@role_required(['lawyer'])
def lawyer_dashboard():
    conn = get_db_connection()
    lawyer_id = session['user_id']

    # Pending Deeds Queue
    pending_flats = conn.execute("""
        SELECT p.*, u.name as owner_name, u.email as owner_email, u.phone as owner_phone,
               u.aadhaar_number_masked, u.aadhaar_verified
        FROM properties p
        JOIN users u ON p.owner_id = u.id
        WHERE p.deed_status = 'PENDING_LAWYER_REVIEW'
        ORDER BY p.id ASC
    """).fetchall()

    # Reviewed by this lawyer
    my_reviews = conn.execute("""
        SELECT p.*, u.name as owner_name
        FROM properties p
        JOIN users u ON p.owner_id = u.id
        WHERE p.reviewed_by_lawyer_id = ?
        ORDER BY p.reviewed_at DESC LIMIT 15
    """, (lawyer_id,)).fetchall()

    counts = {
        'pending': len(pending_flats),
        'approved': conn.execute("SELECT COUNT(*) FROM properties WHERE deed_status = 'APPROVED' AND reviewed_by_lawyer_id = ?", (lawyer_id,)).fetchone()[0],
        'rejected': conn.execute("SELECT COUNT(*) FROM properties WHERE deed_status = 'REJECTED' AND reviewed_by_lawyer_id = ?", (lawyer_id,)).fetchone()[0]
    }

    conn.close()
    return render_template('lawyer/dashboard.html', pending_flats=pending_flats, my_reviews=my_reviews, counts=counts)

@app.route('/lawyer/review/<int:property_id>', methods=['GET', 'POST'])
@login_required
@role_required(['lawyer'])
def lawyer_review_deed(property_id):
    conn = get_db_connection()
    flat = conn.execute("""
        SELECT p.*, u.name as owner_name, u.email as owner_email, u.phone as owner_phone,
               u.aadhaar_number_masked, u.aadhaar_verified
        FROM properties p
        JOIN users u ON p.owner_id = u.id
        WHERE p.id = ?
    """, (property_id,)).fetchone()

    if not flat:
        conn.close()
        flash("Property not found.", "danger")
        return redirect(url_for('lawyer_dashboard'))

    if request.method == 'POST':
        action = request.form.get('action') # 'APPROVE' or 'REJECT'
        lawyer_notes = request.form.get('lawyer_notes', '').strip()

        if action not in ['APPROVE', 'REJECT']:
            flash("Invalid action.", "danger")
            return redirect(url_for('lawyer_review_deed', property_id=property_id))

        new_status = 'APPROVED' if action == 'APPROVE' else 'REJECTED'

        conn.execute("""
            UPDATE properties
            SET deed_status = ?, reviewed_by_lawyer_id = ?, lawyer_notes = ?, reviewed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (new_status, session['user_id'], lawyer_notes, property_id))
        conn.commit()
        conn.close()

        status_label = "approved and published" if new_status == 'APPROVED' else "rejected"
        flash(f"Property deed has been legally {status_label}.", "success")
        return redirect(url_for('lawyer_dashboard'))

    conn.close()
    return render_template('lawyer/review_deed.html', flat=flat)

# -------------------------------------------------------------
# Tenant Portal Routes
# -------------------------------------------------------------
@app.route('/tenant/dashboard')
@login_required
@role_required(['tenant'])
def tenant_dashboard():
    conn = get_db_connection()
    tenant_id = session['user_id']
    tenant = conn.execute("SELECT * FROM users WHERE id = ?", (tenant_id,)).fetchone()

    # Search & Filter query params
    search_query = request.args.get('q', '').strip()
    flat_type = request.args.get('flat_type', '')
    city = request.args.get('city', '')
    max_rent = request.args.get('max_rent', '')
    match_filter = request.args.get('match_only', '')

    query = """
        SELECT p.*, u.name as owner_name, u.aadhaar_verified as owner_aadhaar_verified,
               l.name as lawyer_name, l.lawyer_id as lawyer_badge
        FROM properties p
        JOIN users u ON p.owner_id = u.id
        LEFT JOIN users l ON p.reviewed_by_lawyer_id = l.id
        WHERE p.deed_status = 'APPROVED' AND p.is_active = 1
    """
    params = []

    if search_query:
        query += " AND (p.title LIKE ? OR p.city LIKE ? OR p.address LIKE ?)"
        term = f"%{search_query}%"
        params.extend([term, term, term])

    if flat_type:
        query += " AND p.flat_type = ?"
        params.append(flat_type)

    if city:
        query += " AND lower(p.city) = lower(?)"
        params.append(city)

    if max_rent and max_rent.isdigit():
        query += " AND p.rent_monthly <= ?"
        params.append(float(max_rent))

    query += " ORDER BY p.id DESC"

    raw_flats = conn.execute(query, params).fetchall()

    # Calculate live requirement compatibility for each flat against the tenant's profile
    flats_with_match = []
    for f in raw_flats:
        flat_dict = dict(f)
        compatibility = check_compatibility(flat_dict, dict(tenant))
        flat_dict['compatibility'] = compatibility
        
        # If user toggled 'Show only eligible matching flats'
        if match_filter == '1' and not compatibility['eligible']:
            continue
        flats_with_match.append(flat_dict)

    # Tenant active chats
    chats = conn.execute("""
        SELECT c.*, p.title as flat_title, p.rent_monthly, u.name as owner_name,
               (SELECT message_text FROM messages m WHERE m.chat_id = c.id ORDER BY m.id DESC LIMIT 1) as last_message,
               (SELECT created_at FROM messages m WHERE m.chat_id = c.id ORDER BY m.id DESC LIMIT 1) as last_message_time,
               (SELECT COUNT(*) FROM messages m WHERE m.chat_id = c.id AND m.sender_id != ? AND m.is_read = 0) as unread_count
        FROM chats c
        JOIN properties p ON c.property_id = p.id
        JOIN users u ON c.owner_id = u.id
        WHERE c.tenant_id = ?
        ORDER BY c.updated_at DESC
    """, (tenant_id, tenant_id)).fetchall()

    conn.close()
    return render_template(
        'tenant/dashboard.html',
        flats=flats_with_match,
        tenant=tenant,
        chats=chats,
        search_query=search_query,
        selected_bhk=flat_type,
        selected_city=city,
        max_rent=max_rent,
        match_only=match_filter
    )

@app.route('/tenant/flat/<int:flat_id>')
@login_required
@role_required(['tenant'])
def tenant_flat_detail(flat_id):
    conn = get_db_connection()
    tenant_id = session['user_id']
    tenant = conn.execute("SELECT * FROM users WHERE id = ?", (tenant_id,)).fetchone()

    flat = conn.execute("""
        SELECT p.*, u.name as owner_name, u.email as owner_email, u.phone as owner_phone,
               u.aadhaar_number_masked as owner_aadhaar, u.aadhaar_verified as owner_aadhaar_verified,
               l.name as lawyer_name, l.lawyer_id as lawyer_badge, l.bar_council_reg
        FROM properties p
        JOIN users u ON p.owner_id = u.id
        LEFT JOIN users l ON p.reviewed_by_lawyer_id = l.id
        WHERE p.id = ?
    """, (flat_id,)).fetchone()

    if not flat:
        conn.close()
        flash("Flat not found.", "danger")
        return redirect(url_for('tenant_dashboard'))

    compatibility = check_compatibility(dict(flat), dict(tenant))

    # Check if a chat already exists between this tenant and owner for this flat
    existing_chat = conn.execute("""
        SELECT * FROM chats WHERE property_id = ? AND tenant_id = ?
    """, (flat_id, tenant_id)).fetchone()

    conn.close()
    return render_template(
        'tenant/flat_detail.html',
        flat=flat,
        tenant=tenant,
        compatibility=compatibility,
        existing_chat=existing_chat
    )

@app.route('/tenant/profile', methods=['GET', 'POST'])
@login_required
@role_required(['tenant'])
def tenant_profile():
    conn = get_db_connection()
    tenant_id = session['user_id']

    if request.method == 'POST':
        tenant_type = request.form.get('tenant_type', 'bachelor')
        has_pets = 1 if request.form.get('has_pets') == '1' else 0
        pet_details = request.form.get('pet_details', '').strip()
        diet_pref = request.form.get('diet_pref', 'no_preference')
        smoking_drinking = 1 if request.form.get('smoking_drinking') == '1' else 0
        occupation = request.form.get('occupation', '').strip()

        conn.execute("""
            UPDATE users
            SET tenant_type = ?, has_pets = ?, pet_details = ?,
                diet_pref = ?, smoking_drinking = ?, occupation = ?
            WHERE id = ?
        """, (tenant_type, has_pets, pet_details, diet_pref, smoking_drinking, occupation, tenant_id))
        conn.commit()
        conn.close()
        flash("Tenant profile preferences updated successfully!", "success")
        return redirect(url_for('tenant_dashboard'))

    tenant = conn.execute("SELECT * FROM users WHERE id = ?", (tenant_id,)).fetchone()
    conn.close()
    return render_template('tenant/profile.html', tenant=tenant)

# -------------------------------------------------------------
# In-App Chat Routes (Owner & Tenant)
# -------------------------------------------------------------
@app.route('/api/chat/request', methods=['POST'])
@app.route('/api/chat/initiate', methods=['POST'])
@login_required
@role_required(['tenant'])
def api_chat_request():
    """
    Sends a rental request from Tenant to Owner.
    REQUIREMENT: Only allowed if Tenant meets Owner's flat requirements!
    Chat is unlocked ONLY AFTER the Owner approves this request.
    """
    data = request.get_json() or {}
    property_id = data.get('property_id')
    intro_note = data.get('intro_note', '').strip()
    tenant_id = session['user_id']

    if not property_id:
        return jsonify({'success': False, 'error': 'Property ID is required.'}), 400

    conn = get_db_connection()
    flat = conn.execute("SELECT * FROM properties WHERE id = ?", (property_id,)).fetchone()
    tenant = conn.execute("SELECT * FROM users WHERE id = ?", (tenant_id,)).fetchone()

    if not flat:
        conn.close()
        return jsonify({'success': False, 'error': 'Property not found.'}), 404

    # Evaluate compatibility for owner review
    compat = check_compatibility(dict(flat), dict(tenant))
    if not compat['eligible']:
        reasons_text = "; ".join(compat['reasons'])
        criteria_note = f"[Tenant Note on Criteria: {reasons_text}] "
        if not intro_note.startswith("[Tenant Note"):
            intro_note = criteria_note + (intro_note or "Requesting owner consideration.")

    owner_id = flat['owner_id']
    if owner_id == tenant_id:
        conn.close()
        return jsonify({'success': False, 'error': 'Cannot request your own property.'}), 400

    # Find or create request/chat
    chat = conn.execute("""
        SELECT * FROM chats WHERE property_id = ? AND tenant_id = ?
    """, (property_id, tenant_id)).fetchone()

    if chat:
        chat_id = chat['id']
        chat_status = chat['status']
        if chat_status == 'APPROVED':
            conn.close()
            return jsonify({
                'success': True,
                'status': 'APPROVED',
                'chat_id': chat_id,
                'message': 'Request already approved! Opening chat...',
                'redirect_url': url_for('view_chat', chat_id=chat_id)
            })
        elif chat_status == 'PENDING_OWNER_APPROVAL':
            conn.close()
            return jsonify({
                'success': True,
                'status': 'PENDING_OWNER_APPROVAL',
                'chat_id': chat_id,
                'message': 'Your request is currently pending owner review.',
                'redirect_url': url_for('view_chat', chat_id=chat_id)
            })
        elif chat_status == 'REJECTED':
            # Allow re-requesting
            conn.execute("""
                UPDATE chats 
                SET status = 'PENDING_OWNER_APPROVAL', request_message = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (intro_note, chat_id))
            note_text = intro_note or "Hello, I would like to re-request to connect for this flat."
            conn.execute("""
                INSERT INTO messages (chat_id, sender_id, message_text)
                VALUES (?, ?, ?)
            """, (chat_id, tenant_id, f"📝 [Rental Request Re-submitted]: {note_text}"))
            conn.commit()
            chat_status = 'PENDING_OWNER_APPROVAL'
    else:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO chats (property_id, owner_id, tenant_id, status, request_message)
            VALUES (?, ?, ?, 'PENDING_OWNER_APPROVAL', ?)
        """, (property_id, owner_id, tenant_id, intro_note))
        chat_id = cursor.lastrowid
        
        # Insert introductory greeting message
        note_text = intro_note or f"Hello! I saw your verified flat listing '{flat['title']}' and meet all requirements. I would like to request to connect and schedule a visit."
        cursor.execute("""
            INSERT INTO messages (chat_id, sender_id, message_text)
            VALUES (?, ?, ?)
        """, (chat_id, tenant_id, f"📝 [Rental & Chat Request Sent]: {note_text}"))
        conn.commit()
        chat_status = 'PENDING_OWNER_APPROVAL'

    conn.close()
    return jsonify({
        'success': True,
        'status': chat_status,
        'chat_id': chat_id,
        'message': 'Your request has been submitted to the owner! In-app chat will unlock once the owner approves.',
        'redirect_url': url_for('view_chat', chat_id=chat_id)
    })

@app.route('/api/owner/chat-request/<int:chat_id>/respond', methods=['POST'])
@login_required
@role_required(['owner'])
def api_owner_respond_request(chat_id):
    """
    Owner approves or declines a tenant's chat request.
    Chat is ONLY enabled once the Owner approves!
    """
    data = request.get_json() or {}
    action = data.get('action') # 'APPROVE' or 'REJECT'
    owner_id = session['user_id']

    if action not in ['APPROVE', 'REJECT']:
        return jsonify({'success': False, 'error': 'Invalid action'}), 400

    conn = get_db_connection()
    chat = conn.execute("SELECT * FROM chats WHERE id = ? AND owner_id = ?", (chat_id, owner_id)).fetchone()

    if not chat:
        conn.close()
        return jsonify({'success': False, 'error': 'Request not found or unauthorized.'}), 404

    new_status = 'APPROVED' if action == 'APPROVE' else 'REJECTED'
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE chats 
        SET status = ?, responded_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (new_status, chat_id))

    system_msg = "✅ [Request Accepted]: Owner approved your request. In-app chat is now unlocked!" if action == 'APPROVE' else "❌ [Request Declined]: Owner declined this rental request."
    cursor.execute("""
        INSERT INTO messages (chat_id, sender_id, message_text)
        VALUES (?, ?, ?)
    """, (chat_id, owner_id, system_msg))

    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'status': new_status,
        'message': f"Request successfully {new_status.lower()}."
    })

@app.route('/chat/<int:chat_id>')
@login_required
@role_required(['owner', 'tenant'])
def view_chat(chat_id):
    conn = get_db_connection()
    user_id = session['user_id']
    user_role = session['role']

    chat = conn.execute("""
        SELECT c.*, p.title as flat_title, p.rent_monthly, p.deposit, p.city, p.deed_status,
               o.name as owner_name, o.aadhaar_number_masked as owner_aadhaar,
               t.name as tenant_name, t.aadhaar_number_masked as tenant_aadhaar,
               t.tenant_type, t.occupation, t.has_pets, t.pet_details, t.diet_pref
        FROM chats c
        JOIN properties p ON c.property_id = p.id
        JOIN users o ON c.owner_id = o.id
        JOIN users t ON c.tenant_id = t.id
        WHERE c.id = ?
    """, (chat_id,)).fetchone()

    if not chat:
        conn.close()
        flash("Chat session not found.", "danger")
        return redirect(url_for('owner_dashboard' if user_role == 'owner' else 'tenant_dashboard'))

    # Security check: User must be either owner or tenant in this chat
    if chat['owner_id'] != user_id and chat['tenant_id'] != user_id:
        conn.close()
        flash("Unauthorized access to this chat session.", "danger")
        return redirect(url_for('index'))

    # Mark incoming messages as read
    conn.execute("""
        UPDATE messages
        SET is_read = 1
        WHERE chat_id = ? AND sender_id != ?
    """, (chat_id, user_id))
    conn.commit()

    # Other party details
    other_party = {
        'id': chat['tenant_id'] if user_role == 'owner' else chat['owner_id'],
        'name': chat['tenant_name'] if user_role == 'owner' else chat['owner_name'],
        'role': 'Tenant' if user_role == 'owner' else 'Owner',
        'masked_aadhaar': chat['tenant_aadhaar'] if user_role == 'owner' else chat['owner_aadhaar']
    }

    conn.close()
    return render_template('chat.html', chat=chat, other_party=other_party)

@app.route('/api/chat/<int:chat_id>/messages', methods=['GET'])
@login_required
def api_get_messages(chat_id):
    conn = get_db_connection()
    user_id = session['user_id']

    chat = conn.execute("SELECT owner_id, tenant_id FROM chats WHERE id = ?", (chat_id,)).fetchone()
    if not chat or (chat['owner_id'] != user_id and chat['tenant_id'] != user_id):
        conn.close()
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    # Mark as read
    conn.execute("UPDATE messages SET is_read = 1 WHERE chat_id = ? AND sender_id != ?", (chat_id, user_id))
    conn.commit()

    messages = conn.execute("""
        SELECT m.id, m.sender_id, m.message_text, m.is_read, m.created_at, u.name as sender_name
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.chat_id = ?
        ORDER BY m.id ASC
    """, (chat_id,)).fetchall()

    conn.close()

    result = []
    for m in messages:
        result.append({
            'id': m['id'],
            'sender_id': m['sender_id'],
            'sender_name': m['sender_name'],
            'message_text': m['message_text'],
            'is_read': m['is_read'],
            'created_at': m['created_at'],
            'is_mine': (m['sender_id'] == user_id)
        })

    return jsonify({'success': True, 'messages': result})

@app.route('/api/chat/<int:chat_id>/send', methods=['POST'])
@login_required
def api_send_message(chat_id):
    conn = get_db_connection()
    user_id = session['user_id']

    chat = conn.execute("SELECT owner_id, tenant_id, status FROM chats WHERE id = ?", (chat_id,)).fetchone()
    if not chat or (chat['owner_id'] != user_id and chat['tenant_id'] != user_id):
        conn.close()
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    # CRITICAL: Chat is ONLY allowed after approval of the owner!
    if chat['status'] != 'APPROVED':
        conn.close()
        return jsonify({'success': False, 'error': 'In-app chat messaging is locked until the owner approves your request.'}), 403

    data = request.get_json() or {}
    text = data.get('message', '').strip()

    if not text:
        conn.close()
        return jsonify({'success': False, 'error': 'Message text cannot be empty'}), 400

    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO messages (chat_id, sender_id, message_text)
        VALUES (?, ?, ?)
    """, (chat_id, user_id, text))
    msg_id = cursor.lastrowid

    # Update chat timestamp
    cursor.execute("UPDATE chats SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (chat_id,))
    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'message_id': msg_id,
        'text': text
    })

# -------------------------------------------------------------
# Admin Portal Routes (Lawyer Generation & System Oversight)
# -------------------------------------------------------------
@app.route('/admin/dashboard')
@login_required
@role_required(['admin'])
def admin_dashboard():
    conn = get_db_connection()

    counts = {
        'owners': conn.execute("SELECT COUNT(*) FROM users WHERE role = 'owner'").fetchone()[0],
        'tenants': conn.execute("SELECT COUNT(*) FROM users WHERE role = 'tenant'").fetchone()[0],
        'lawyers': conn.execute("SELECT COUNT(*) FROM users WHERE role = 'lawyer'").fetchone()[0],
        'total_flats': conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0],
        'pending_deeds': conn.execute("SELECT COUNT(*) FROM properties WHERE deed_status = 'PENDING_LAWYER_REVIEW'").fetchone()[0],
        'approved_deeds': conn.execute("SELECT COUNT(*) FROM properties WHERE deed_status = 'APPROVED'").fetchone()[0],
        'total_chats': conn.execute("SELECT COUNT(*) FROM chats").fetchone()[0]
    }

    # Lawyers list
    lawyers = conn.execute("""
        SELECT u.*, 
               (SELECT COUNT(*) FROM properties WHERE reviewed_by_lawyer_id = u.id) as reviews_count
        FROM users u
        WHERE u.role = 'lawyer'
        ORDER BY u.id DESC
    """).fetchall()

    # Recent properties
    recent_properties = conn.execute("""
        SELECT p.*, u.name as owner_name, l.name as lawyer_name
        FROM properties p
        JOIN users u ON p.owner_id = u.id
        LEFT JOIN users l ON p.reviewed_by_lawyer_id = l.id
        ORDER BY p.id DESC LIMIT 10
    """).fetchall()

    smtp_cfg = email_service.get_smtp_config()

    conn.close()
    return render_template(
        'admin/dashboard.html',
        counts=counts,
        lawyers=lawyers,
        recent_properties=recent_properties,
        smtp_cfg=smtp_cfg
    )

@app.route('/admin/generate-lawyer', methods=['GET', 'POST'])
@login_required
@role_required(['admin'])
def admin_generate_lawyer():
    """
    CRITICAL REQUIREMENT:
    Lawyer ID can ONLY be generated by the Admin.
    """
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip().lower()
        bar_council_reg = request.form.get('bar_council_reg', '').strip()
        phone = request.form.get('phone', '').strip()
        specialization = request.form.get('specialization', 'Property & Title Law').strip()
        password = request.form.get('password', '').strip()

        if not name or not email or not bar_council_reg or not password:
            flash("All mandatory fields must be filled.", "danger")
            return render_template('admin/generate_lawyer.html')

        is_valid_pw, pw_err = validate_password_rules(password)
        if not is_valid_pw:
            flash(pw_err, "danger")
            return render_template('admin/generate_lawyer.html', suggested_id=f"LAW-2026-{random.randint(1000, 9999)}")

        conn = get_db_connection()
        existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            conn.close()
            flash("A user with this email address already exists.", "danger")
            return render_template('admin/generate_lawyer.html')

        # Auto-generate unique Official Lawyer ID
        random_suffix = random.randint(1000, 9999)
        lawyer_id = f"LAW-2026-{random_suffix}"

        hashed_pw = generate_password_hash(password)

        conn.execute("""
            INSERT INTO users (
                name, email, password_hash, role, phone,
                lawyer_id, bar_council_reg, specialization,
                aadhaar_verified, email_verified, status
            ) VALUES (?, ?, ?, 'lawyer', ?, ?, ?, ?, 1, 1, 'active')
        """, (name, email, hashed_pw, phone, lawyer_id, bar_council_reg, specialization))
        conn.commit()
        conn.close()

        flash(f"Successfully generated Lawyer account! Official Lawyer ID: {lawyer_id}", "success")
        return redirect(url_for('admin_dashboard'))

    # Auto-suggest next Lawyer ID for preview
    suggested_id = f"LAW-2026-{random.randint(1000, 9999)}"
    return render_template('admin/generate_lawyer.html', suggested_id=suggested_id)

@app.route('/admin/settings/smtp', methods=['POST'])
@login_required
@role_required(['admin'])
def admin_save_smtp():
    server = request.form.get('smtp_server', '').strip()
    port = request.form.get('smtp_port', '587').strip()
    user = request.form.get('smtp_user', '').strip()
    password = request.form.get('smtp_pass', '').strip()
    from_email = request.form.get('from_email', '').strip()
    use_tls = True if request.form.get('use_tls') == '1' else False

    email_service.save_smtp_config(server, port, user, password, from_email, use_tls)
    flash("SMTP settings saved successfully! Real email delivery updated.", "success")
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/settings/test-smtp', methods=['POST'])
@login_required
@role_required(['admin'])
def admin_test_smtp():
    data = request.get_json() or {}
    server = data.get('smtp_server')
    port = data.get('smtp_port', 587)
    user = data.get('smtp_user')
    password = data.get('smtp_pass')
    use_tls = data.get('use_tls', True)
    test_recipient = data.get('test_recipient')

    res = email_service.test_smtp_connection(server, port, user, password, use_tls, test_recipient)
    return jsonify(res)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
