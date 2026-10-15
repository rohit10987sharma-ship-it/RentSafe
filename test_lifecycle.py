import unittest
import json
import io
import os
from app import app
from database import init_db, get_db_connection
from seed_data import seed_database
from config import Config

class RentSafeFullLifecycleTestCase(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        seed_database()
        # Clean up any lingering test flat from previous test executions
        conn = get_db_connection()
        conn.execute("DELETE FROM properties WHERE title LIKE '%Hiranandani%'")
        conn.commit()
        conn.close()

    def test_complete_deed_verification_lifecycle(self):
        """
        End-to-End test:
        1. Owner logs in and lists a new flat with a Deed document upload.
        2. Flat starts in PENDING_LAWYER_REVIEW and is NOT visible on public tenant browse.
        3. Panel Lawyer logs in, reviews the deed and owner Aadhaar verification.
        4. Lawyer approves the deed with legal certificate notes.
        5. Flat becomes APPROVED and visible on tenant browse.
        6. Tenant matching criteria is evaluated and in-app chat is initiated.
        """
        # 1. Owner logs in
        login_res = self.client.post('/login', data={
            'role': 'owner',
            'identifier': 'owner.vikram@gmail.com',
            'password': 'owner123'
        }, follow_redirects=True)
        self.assertEqual(login_res.status_code, 200)

        # 2. Owner lists new flat with Deed upload
        deed_content = b"GOVERNMENT OF MAHARASHTRA REGISTERED TITLE DEED No 99201"
        data = {
            'title': 'Sunny 2 BHK in Hiranandani Estate, Thane',
            'description': 'High floor with creek view, modular kitchen.',
            'flat_type': '2 BHK',
            'furnishing': 'Fully Furnished',
            'rent_monthly': '38000',
            'deposit': '100000',
            'address': 'Flat 1802, Rodas Enclave',
            'city': 'Thane',
            'pincode': '400607',
            'req_pets': 'allowed',
            'req_tenant_type': 'open_to_all',
            'req_food': 'no_restriction',
            'req_smoking_drinking': 'prohibited',
            'req_notes': 'Maintain quiet hours after 10 PM',
            'deed_document': (io.BytesIO(deed_content), 'Hiranandani_Sale_Deed.pdf')
        }
        create_res = self.client.post('/owner/add-flat', data=data, content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(create_res.status_code, 200)

        # Verify property is saved as PENDING_LAWYER_REVIEW
        conn = get_db_connection()
        new_flat = conn.execute("SELECT * FROM properties WHERE title LIKE '%Hiranandani%' ORDER BY id DESC LIMIT 1").fetchone()
        self.assertIsNotNone(new_flat)
        self.assertEqual(new_flat['deed_status'], 'PENDING_LAWYER_REVIEW')
        new_flat_id = new_flat['id']

        # 3. Check that pending flat is NOT visible on public index or tenant dashboard
        public_res = self.client.get('/')
        self.assertNotIn(b'Hiranandani', public_res.data)

        # 4. Lawyer logs in
        self.client.get('/logout')
        lawyer_login = self.client.post('/login', data={
            'role': 'lawyer',
            'identifier': 'LAW-2026-7841',
            'password': 'lawyer123'
        }, follow_redirects=True)
        self.assertEqual(lawyer_login.status_code, 200)

        # Lawyer reviews and approves deed
        approve_res = self.client.post(f'/lawyer/review/{new_flat_id}', data={
            'action': 'APPROVE',
            'lawyer_notes': 'Inspected Sub-Registrar seal Thane. Clear freehold title under Vikramaditya Singhania.'
        }, follow_redirects=True)
        self.assertEqual(approve_res.status_code, 200)

        # 5. Check flat status updated to APPROVED
        conn = get_db_connection()
        approved_flat = conn.execute("SELECT * FROM properties WHERE id = ?", (new_flat_id,)).fetchone()
        conn.close()
        self.assertEqual(approved_flat['deed_status'], 'APPROVED')

        # 6. Tenant logs in and checks compatibility
        self.client.get('/logout')
        tenant_login = self.client.post('/login', data={
            'role': 'tenant',
            'identifier': 'tenant.rohit@gmail.com',
            'password': 'tenant123'
        }, follow_redirects=True)
        self.assertEqual(tenant_login.status_code, 200)

        # Flat is now visible to tenant!
        detail_res = self.client.get(f'/tenant/flat/{new_flat_id}')
        self.assertEqual(detail_res.status_code, 200)
        self.assertIn(b'Hiranandani', detail_res.data)
        self.assertIn(b'100% Match', detail_res.data)

        # 7. Tenant sends connection request to Owner
        chat_init_res = self.client.post('/api/chat/request', json={
            'property_id': new_flat_id,
            'intro_note': 'Interested in renting your Hiranandani flat.'
        })
        self.assertEqual(chat_init_res.status_code, 200)
        chat_id = chat_init_res.get_json()['chat_id']
        self.assertEqual(chat_init_res.get_json()['status'], 'PENDING_OWNER_APPROVAL')

        # 8. Owner logs in and approves tenant request
        self.client.get('/logout')
        self.client.post('/login', data={
            'role': 'owner',
            'identifier': 'owner.vikram@gmail.com',
            'password': 'owner123'
        }, follow_redirects=True)

        approve_req_res = self.client.post(f'/api/owner/chat-request/{chat_id}/respond', json={
            'action': 'APPROVE'
        })
        self.assertEqual(approve_req_res.status_code, 200)

        # 9. Tenant logs back in and sends messages in now-unlocked in-app chat
        self.client.get('/logout')
        self.client.post('/login', data={
            'role': 'tenant',
            'identifier': 'tenant.rohit@gmail.com',
            'password': 'tenant123'
        }, follow_redirects=True)

        send_res = self.client.post(f'/api/chat/{chat_id}/send', json={
            'message': 'Hi Vikramaditya, is the flat available for possession immediately?'
        })
        self.assertEqual(send_res.status_code, 200)

        # Fetch messages
        messages_res = self.client.get(f'/api/chat/{chat_id}/messages')
        self.assertEqual(messages_res.status_code, 200)
        msgs = messages_res.get_json()['messages']
        self.assertTrue(any('possession' in m['message_text'] for m in msgs))

if __name__ == '__main__':
    unittest.main()
