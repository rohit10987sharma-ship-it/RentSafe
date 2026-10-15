import sqlite3
import os
import time
from config import Config

def get_db_connection():
    """Returns a sqlite3 connection with Row factory enabled."""
    conn = sqlite3.connect(Config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    """Initializes all database tables and ensures directories exist."""
    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(Config.DEEDS_FOLDER, exist_ok=True)
    os.makedirs(Config.PROPERTIES_FOLDER, exist_ok=True)

    conn = get_db_connection()
    cursor = conn.cursor()

    # Users Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('admin', 'lawyer', 'owner', 'tenant')),
        phone TEXT,
        lawyer_id TEXT UNIQUE,
        bar_council_reg TEXT,
        specialization TEXT,
        aadhaar_number_masked TEXT,
        aadhaar_verified INTEGER DEFAULT 0,
        email_verified INTEGER DEFAULT 0,
        tenant_type TEXT DEFAULT 'bachelor',
        has_pets INTEGER DEFAULT 0,
        pet_details TEXT DEFAULT '',
        diet_pref TEXT DEFAULT 'no_preference',
        smoking_drinking INTEGER DEFAULT 0,
        occupation TEXT DEFAULT '',
        status TEXT DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Email OTPs Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS email_otps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL,
        otp_code TEXT NOT NULL,
        purpose TEXT DEFAULT 'registration',
        expires_at REAL NOT NULL,
        verified INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Properties Table with Requirements and Deed Verification
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS properties (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        flat_type TEXT NOT NULL,
        furnishing TEXT NOT NULL,
        rent_monthly REAL NOT NULL,
        deposit REAL NOT NULL,
        address TEXT NOT NULL,
        city TEXT NOT NULL,
        pincode TEXT,
        image_path TEXT,
        req_pets TEXT NOT NULL DEFAULT 'not_allowed',
        req_tenant_type TEXT NOT NULL DEFAULT 'open_to_all',
        req_food TEXT NOT NULL DEFAULT 'no_restriction',
        req_smoking_drinking TEXT NOT NULL DEFAULT 'prohibited',
        req_notes TEXT,
        deed_filename TEXT NOT NULL,
        deed_original_name TEXT,
        deed_status TEXT DEFAULT 'PENDING_LAWYER_REVIEW' CHECK(deed_status IN ('PENDING_LAWYER_REVIEW', 'APPROVED', 'REJECTED')),
        reviewed_by_lawyer_id INTEGER,
        lawyer_notes TEXT,
        reviewed_at TIMESTAMP,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (reviewed_by_lawyer_id) REFERENCES users(id) ON DELETE SET NULL
    );
    """)

    # In-App Chats Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        property_id INTEGER NOT NULL,
        owner_id INTEGER NOT NULL,
        tenant_id INTEGER NOT NULL,
        status TEXT DEFAULT 'PENDING_OWNER_APPROVAL' CHECK(status IN ('PENDING_OWNER_APPROVAL', 'APPROVED', 'REJECTED')),
        request_message TEXT DEFAULT '',
        responded_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (property_id) REFERENCES properties(id) ON DELETE CASCADE,
        FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (tenant_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE (property_id, tenant_id)
    );
    """)

    # Safe column migrations for existing databases
    try:
        cursor.execute("ALTER TABLE chats ADD COLUMN status TEXT DEFAULT 'PENDING_OWNER_APPROVAL'")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE chats ADD COLUMN request_message TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE chats ADD COLUMN responded_at TIMESTAMP")
    except sqlite3.OperationalError:
        pass

    # Messages Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        sender_id INTEGER NOT NULL,
        message_text TEXT NOT NULL,
        is_read INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE,
        FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE
    );
    """)

    conn.commit()
    conn.close()

def save_email_otp(email: str, otp_code: str, purpose: str = "registration", validity_seconds: int = 600):
    """Saves or updates email OTP with expiration timestamp."""
    conn = get_db_connection()
    cursor = conn.cursor()
    expires_at = time.time() + validity_seconds
    
    # Invalidate previous unverified OTPs for this email and purpose
    cursor.execute("DELETE FROM email_otps WHERE email = ? AND purpose = ?", (email.lower().strip(), purpose))
    
    cursor.execute("""
        INSERT INTO email_otps (email, otp_code, purpose, expires_at, verified)
        VALUES (?, ?, ?, ?, 0)
    """, (email.lower().strip(), otp_code, purpose, expires_at))
    conn.commit()
    conn.close()

def verify_email_otp_db(email: str, entered_otp: str, purpose: str = "registration"):
    """Validates the entered email OTP against the database record."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now = time.time()

    cursor.execute("""
        SELECT id, otp_code, expires_at, verified 
        FROM email_otps 
        WHERE email = ? AND purpose = ?
        ORDER BY id DESC LIMIT 1
    """, (email.lower().strip(), purpose))
    
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {"success": False, "error": "No OTP found for this email. Please request a new OTP."}

    if row["verified"] == 1:
        conn.close()
        return {"success": True, "message": "Email already verified."}

    if now > row["expires_at"]:
        conn.close()
        return {"success": False, "error": "OTP has expired. Please request a new one."}

    if row["otp_code"].strip() == entered_otp.strip():
        cursor.execute("UPDATE email_otps SET verified = 1 WHERE id = ?", (row["id"],))
        conn.commit()
        conn.close()
        return {"success": True, "message": "Email successfully verified!"}
    else:
        conn.close()
        return {"success": False, "error": "Incorrect OTP code. Please enter the valid 6-digit OTP sent to your mail."}

def check_compatibility(flat_dict, tenant_dict):
    """
    Evaluates whether the tenant meets the owner's flat listing requirements.
    Returns:
      {
         'eligible': bool,
         'score': int (percentage 0-100),
         'reasons': list of str,
         'breakdown': {
             'pets': {'pass': bool, 'text': str},
             'tenant_type': {'pass': bool, 'text': str},
             'food': {'pass': bool, 'text': str},
             'smoking': {'pass': bool, 'text': str}
         }
      }
    """
    eligible = True
    reasons = []
    total_checks = 4
    passed_checks = 0
    breakdown = {}

    # 1. Pet Requirement
    req_pets = flat_dict.get('req_pets', 'not_allowed')
    tenant_has_pets = bool(tenant_dict.get('has_pets', 0))
    if req_pets == 'not_allowed' and tenant_has_pets:
        eligible = False
        reasons.append("Owner does not allow pets.")
        breakdown['pets'] = {'pass': False, 'text': 'Pets strictly not allowed for this flat.'}
    else:
        passed_checks += 1
        breakdown['pets'] = {'pass': True, 'text': 'Pet criteria satisfied.'}

    # 2. Tenant Category Requirement
    req_type = flat_dict.get('req_tenant_type', 'open_to_all')
    tenant_type = tenant_dict.get('tenant_type', 'bachelor')
    if req_type == 'family_only' and tenant_type != 'family':
        eligible = False
        reasons.append("Flat is reserved for Families only.")
        breakdown['tenant_type'] = {'pass': False, 'text': 'Owner accepts Families only.'}
    elif req_type == 'bachelors_allowed' or req_type == 'open_to_all':
        passed_checks += 1
        breakdown['tenant_type'] = {'pass': True, 'text': 'Tenant category accepted.'}
    elif req_type == 'female_only' and tenant_type != 'female_tenant':
        # Conditional check if applicable
        passed_checks += 1
        breakdown['tenant_type'] = {'pass': True, 'text': 'Tenant category accepted.'}
    else:
        passed_checks += 1
        breakdown['tenant_type'] = {'pass': True, 'text': 'Tenant category matches.'}

    # 3. Food Preference
    req_food = flat_dict.get('req_food', 'no_restriction')
    tenant_diet = tenant_dict.get('diet_pref', 'no_preference')
    if req_food == 'veg_only' and tenant_diet == 'non_veg':
        eligible = False
        reasons.append("Owner requires Pure Vegetarian tenants.")
        breakdown['food'] = {'pass': False, 'text': 'Owner allows vegetarian cooking only.'}
    else:
        passed_checks += 1
        breakdown['food'] = {'pass': True, 'text': 'Dietary preference compatible.'}

    # 4. Smoking / Drinking
    req_smoking = flat_dict.get('req_smoking_drinking', 'prohibited')
    tenant_smokes = bool(tenant_dict.get('smoking_drinking', 0))
    if req_smoking == 'prohibited' and tenant_smokes:
        eligible = False
        reasons.append("Smoking/Drinking is strictly prohibited on the premises.")
        breakdown['smoking'] = {'pass': False, 'text': 'Smoking/Drinking strictly not allowed.'}
    else:
        passed_checks += 1
        breakdown['smoking'] = {'pass': True, 'text': 'House policy compatible.'}

    score = int((passed_checks / total_checks) * 100)
    return {
        'eligible': eligible,
        'score': score,
        'reasons': reasons,
        'breakdown': breakdown
    }
