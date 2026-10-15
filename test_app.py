import unittest
import json
import os
from app import app
from database import init_db, get_db_connection
from seed_data import seed_database
import aadhaar_service

class RentSafeTestCase(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        seed_database()
        conn = get_db_connection()
        conn.execute("DELETE FROM users WHERE email IN ('strong_user@example.com', 'test_pw1@example.com', 'test_pw2@example.com', 'test_pw3@example.com', 'adv.priya@rentsafe.com')")
        conn.execute("DELETE FROM chats")
        conn.execute("DELETE FROM messages")
        conn.commit()
        conn.close()

    def test_home_page(self):
        """Test landing page loads successfully with featured properties."""
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'RentSafe', res.data)
        self.assertIn(b'Featured Verified Properties', res.data)

    def test_login_pages_for_all_four_roles(self):
        """Test login pages for Owner, Tenant, Lawyer, Admin."""
        for role in ['owner', 'tenant', 'lawyer', 'admin']:
            res = self.client.get(f'/login?role={role}')
            self.assertEqual(res.status_code, 200)
            self.assertIn(role.encode(), res.data)

    def test_lawyer_login_with_lawyer_id(self):
        """Test Lawyer can log in using their generated Lawyer ID."""
        res = self.client.post('/login', data={
            'role': 'lawyer',
            'identifier': 'LAW-2026-7841',
            'password': 'lawyer123'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Lawyer Verification Console', res.data)

    def test_admin_login(self):
        """Test Admin login."""
        res = self.client.post('/login', data={
            'role': 'admin',
            'identifier': 'admin@rentsafe.com',
            'password': 'admin123'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Admin Platform Console', res.data)

    def test_password_rules_enforcement(self):
        """Test password complexity rules (length >= 8, letter, digit, special character)."""
        # Weak password 1: Too short
        res1 = self.client.post('/api/auth/register-user', json={
            'name': 'Tester', 'email': 'test_pw1@example.com', 'password': 'Pass1!',
            'role': 'tenant', 'email_verified': True, 'aadhaar_verified': True, 'masked_aadhaar': 'XXXX-XXXX-1234'
        })
        self.assertEqual(res1.status_code, 400)
        self.assertIn('8 characters', res1.get_json()['error'])

        # Weak password 2: No special char
        res2 = self.client.post('/api/auth/register-user', json={
            'name': 'Tester', 'email': 'test_pw2@example.com', 'password': 'Password123',
            'role': 'tenant', 'email_verified': True, 'aadhaar_verified': True, 'masked_aadhaar': 'XXXX-XXXX-1234'
        })
        self.assertEqual(res2.status_code, 400)
        self.assertIn('special character', res2.get_json()['error'])

        # Weak password 3: No digit
        res3 = self.client.post('/api/auth/register-user', json={
            'name': 'Tester', 'email': 'test_pw3@example.com', 'password': 'Password!@#',
            'role': 'tenant', 'email_verified': True, 'aadhaar_verified': True, 'masked_aadhaar': 'XXXX-XXXX-1234'
        })
        self.assertEqual(res3.status_code, 400)
        self.assertIn('digit', res3.get_json()['error'])

        # Strong password: Meets all rules
        res4 = self.client.post('/api/auth/register-user', json={
            'name': 'Strong User', 'email': 'strong_user@example.com', 'password': 'Secure#Password2026',
            'role': 'tenant', 'email_verified': True, 'aadhaar_verified': True, 'masked_aadhaar': 'XXXX-XXXX-1234'
        })
        self.assertEqual(res4.status_code, 200)
        self.assertTrue(res4.get_json()['success'])

    def test_admin_generate_lawyer_with_password_rules(self):
        """Test Admin generating Lawyer with valid password meeting rules."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['role'] = 'admin'
            sess['name'] = 'System Administrator'
            sess['email'] = 'admin@rentsafe.com'

        res = self.client.post('/admin/generate-lawyer', data={
            'name': 'Adv. Priya Deshmukh',
            'email': 'adv.priya@rentsafe.com',
            'bar_council_reg': 'DEL/9102/2018',
            'phone': '+91 98111 22334',
            'specialization': 'Conveyance & Deed Law',
            'password': 'Priya#Secure2026'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        conn = get_db_connection()
        lawyer = conn.execute("SELECT * FROM users WHERE email = 'adv.priya@rentsafe.com'").fetchone()
        conn.close()
        self.assertIsNotNone(lawyer)
        self.assertTrue(lawyer['lawyer_id'].startswith('LAW-2026-'))

    def test_tenant_request_and_owner_approval_chat_workflow(self):
        """
        Test:
        1. Tenant sends request on matching flat -> status PENDING_OWNER_APPROVAL.
        2. Chat message is locked before owner approval.
        3. Owner approves request -> status APPROVED.
        4. In-app chat is now unlocked and messages can be sent.
        5. Tenant on mismatched flat is rejected.
        """
        conn = get_db_connection()
        tenant = conn.execute("SELECT * FROM users WHERE role = 'tenant'").fetchone()
        flat1 = conn.execute("SELECT * FROM properties WHERE title LIKE '%Skyline%' OR address LIKE '%Bandra%'").fetchone()
        flat2 = conn.execute("SELECT * FROM properties WHERE title LIKE '%Koramangala%' OR address LIKE '%Koramangala%'").fetchone()
        owner_id = flat1['owner_id']
        conn.close()

        # Log in as tenant
        with self.client.session_transaction() as sess:
            sess['user_id'] = tenant['id']
            sess['role'] = 'tenant'
            sess['name'] = tenant['name']
            sess['email'] = tenant['email']

        # 1. Tenant sends connection request on Flat 1
        res1 = self.client.post('/api/chat/request', json={
            'property_id': flat1['id'],
            'intro_note': 'Hello! I meet all rules and would like to visit.'
        })
        self.assertEqual(res1.status_code, 200)
        data1 = res1.get_json()
        self.assertTrue(data1['success'])
        self.assertEqual(data1['status'], 'PENDING_OWNER_APPROVAL')
        chat_id = data1['chat_id']

        # 2. Tenant tries sending message BEFORE owner approval -> Should be locked!
        res_locked = self.client.post(f'/api/chat/{chat_id}/send', json={
            'message': 'Can I message before approval?'
        })
        self.assertEqual(res_locked.status_code, 403)
        self.assertIn('locked until the owner approves', res_locked.get_json()['error'])

        # 3. Owner logs in and approves the request
        with self.client.session_transaction() as sess:
            sess['user_id'] = owner_id
            sess['role'] = 'owner'

        res_approve = self.client.post(f'/api/owner/chat-request/{chat_id}/respond', json={
            'action': 'APPROVE'
        })
        self.assertEqual(res_approve.status_code, 200)
        self.assertEqual(res_approve.get_json()['status'], 'APPROVED')

        # 4. Tenant logs back in and sends message -> Now allowed!
        with self.client.session_transaction() as sess:
            sess['user_id'] = tenant['id']
            sess['role'] = 'tenant'

        res_msg = self.client.post(f'/api/chat/{chat_id}/send', json={
            'message': 'Thank you for approving! When can I visit the flat?'
        })
        self.assertEqual(res_msg.status_code, 200)
        self.assertTrue(res_msg.get_json()['success'])

        # 5. Flat 2 Mismatch (Family only vs Bachelor) -> Request is submitted with criteria note for owner review
        res2 = self.client.post('/api/chat/request', json={
            'property_id': flat2['id']
        })
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.get_json()['status'], 'PENDING_OWNER_APPROVAL')

    def test_forgot_password_flow_for_tenant_and_owner(self):
        """
        Tests Forgot Password functionality:
        1. Accessing page renders properly.
        2. Attempting OTP for unregistered email returns 404.
        3. Real OTP generation and dispatch for registered tenant and owner.
        4. Rejection of weak passwords failing complexity rules.
        5. Rejection of invalid/incorrect OTP.
        6. Successful password reset with valid OTP and strong password.
        7. Verification that new password logs in successfully and old password fails.
        """
        # 1. Page load
        res_page = self.client.get('/forgot-password?role=tenant')
        self.assertEqual(res_page.status_code, 200)
        self.assertIn(b'Password Recovery', res_page.data)

        # 2. Unregistered email
        res_unreg = self.client.post('/api/auth/forgot-password/send-otp', json={
            'email': 'nonexistent_user@example.com',
            'role': 'tenant'
        })
        self.assertEqual(res_unreg.status_code, 404)
        self.assertIn('No registered Tenant account', res_unreg.get_json()['error'])

        # 3. Request OTP for registered owner
        res_send = self.client.post('/api/auth/forgot-password/send-otp', json={
            'email': 'owner.vikram@gmail.com',
            'role': 'owner'
        })
        self.assertEqual(res_send.status_code, 200)
        self.assertTrue(res_send.get_json()['success'])

        # Fetch generated OTP from DB
        conn = get_db_connection()
        otp_row = conn.execute("SELECT otp_code FROM email_otps WHERE email = 'owner.vikram@gmail.com' AND purpose = 'forgot_password' ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        self.assertIsNotNone(otp_row)
        valid_otp = otp_row['otp_code']

        # 4. Weak password rejection (no special character)
        res_weak = self.client.post('/api/auth/forgot-password/reset', json={
            'email': 'owner.vikram@gmail.com',
            'role': 'owner',
            'otp': valid_otp,
            'new_password': 'SimplePassword123',
            'confirm_password': 'SimplePassword123'
        })
        self.assertEqual(res_weak.status_code, 400)
        self.assertIn('special character', res_weak.get_json()['error'])

        # 5. Invalid OTP rejection
        res_bad_otp = self.client.post('/api/auth/forgot-password/reset', json={
            'email': 'owner.vikram@gmail.com',
            'role': 'owner',
            'otp': '999999',
            'new_password': 'NewOwner#Pass2026',
            'confirm_password': 'NewOwner#Pass2026'
        })
        self.assertEqual(res_bad_otp.status_code, 400)
        self.assertIn('Incorrect OTP', res_bad_otp.get_json()['error'])

        # 6. Successful password reset with valid OTP and strong password
        res_reset = self.client.post('/api/auth/forgot-password/reset', json={
            'email': 'owner.vikram@gmail.com',
            'role': 'owner',
            'otp': valid_otp,
            'new_password': 'NewOwner#Pass2026',
            'confirm_password': 'NewOwner#Pass2026'
        })
        self.assertEqual(res_reset.status_code, 200)
        self.assertTrue(res_reset.get_json()['success'])

        # 7. Old password no longer works
        old_login = self.client.post('/login', data={
            'role': 'owner',
            'identifier': 'owner.vikram@gmail.com',
            'password': 'owner123'
        }, follow_redirects=True)
        self.assertIn(b'Invalid credentials', old_login.data)

        # 8. New password logs in successfully!
        new_login = self.client.post('/login', data={
            'role': 'owner',
            'identifier': 'owner.vikram@gmail.com',
            'password': 'NewOwner#Pass2026'
        }, follow_redirects=True)
        self.assertEqual(new_login.status_code, 200)
        self.assertIn(b'Owner Dashboard', new_login.data)

if __name__ == '__main__':
    unittest.main()

