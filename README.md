# RentSafe - Legal Property Rental & Verification Platform

A comprehensive real-estate rental and legal deed verification platform built with **Python (Flask), HTML5, CSS3, and JavaScript**.

---

## 🌟 Key Features

### 1. Four Distinct Login Portals (`/login`)
- **Owner Login**: Manage listed flats, deed status, and incoming tenant chats.
- **Tenant Login**: Browse lawyer-verified properties, check requirement matches, and chat with owners.
- **Lawyer Login**: Authenticate with unique **Lawyer ID** (e.g. `LAW-2026-7841`) to review and certify property deeds.
- **Admin Login**: Platform control, panel lawyer account generation, and SMTP settings.

### 2. Admin-Exclusive Lawyer ID Generation
- Lawyers **cannot self-register**.
- Only the Admin can generate official Lawyer accounts and issue unique IDs (format: `LAW-2026-XXXX`).

### 3. Multi-Step Verification & Password Security
- **Strict Password Rules**:
  - Enforces minimum 8 characters, at least one letter (`a-z, A-Z`), at least one numeric digit (`0-9`), and at least one special character (`!@#$%^&*`).
  - Interactive live checklist on registration and lawyer creation pages.
- **Real Email OTP Verification**:
  - Sends a real 6-digit one-time passcode to the user's email address via `smtplib`.
  - **Security Guarantee**: The OTP is **never displayed on the screen or dashboard** and is not exposed in the API response.
- **Aadhaar Card OTP Verification**:
  - Validates 12-digit Indian national identity number.
  - Sends OTP to simulated registered mobile linked with UIDAI (e.g. `+91 98*** ***47`).
  - Stores masked Aadhaar (`XXXX-XXXX-1234`) and sets verified badge.

### 4. Owner Flat Listing & Mandatory Deed Verification
- Owners list flats with specific criteria:
  - **Pet Policy**: (Allowed / Strictly Not Allowed / Conditional)
  - **Tenant Preference**: (Open to All / Family Only / Working Bachelors Allowed / Female Only)
  - **Food / Diet**: (No Restriction / Strictly Vegetarian Only / Non-Veg Allowed)
  - **House Conduct**: (Smoking & Drinking Prohibited / Balcony Only)
- **Mandatory Deed Upload**: Every flat requires uploading a registered Title Deed document (PDF, JPG, PNG).
- Listing enters `PENDING_LAWYER_REVIEW` and is forwarded to the panel Lawyer's queue.
- The flat **cannot be seen by tenants** until approved by a lawyer!

### 5. Lawyer Review Console
- Panel advocates inspect uploaded deed files and verify ownership against the owner's UIDAI-verified Aadhaar name.
- Lawyers can **Certify & Approve** (affixing their Advocate Name, Lawyer ID, and legal notes) or **Reject** with reasons.
- Once certified, the flat is published with a green **"Lawyer Deed Verified"** badge.

### 6. Tenant Request Option & Chat Allowed Only After Owner Approval
- **Requirement Compatibility Check**: The engine checks tenant profile attributes against owner flat rules.
- **Tenant Rental Request**: If criteria match, the tenant submits a **Rental & Chat Request** (with an optional introductory note).
- **Owner Review & Gate**:
  - The Owner receives the request in their dashboard with the tenant's verified Aadhaar status, lifestyle profile, and message.
  - Owner clicks **"Approve Request & Allow Chat"** or **"Decline"**.
- **Chat Unlocked ONLY After Owner Approval**:
  - While pending, in-app chat is safely locked with status tracking.
  - Once the owner approves, full real-time in-app chat is instantly unlocked!

### 5. Forgot Password & OTP Account Recovery
- Dedicated self-service password reset for **Tenant** and **Owner** accounts via registered email.
- Real 6-digit email OTP verification.
- Enforces password complexity rules (length >= 8, letter, digit, special character) on password regeneration.

---

## 🚀 How to Run in Visual Studio Code (VS Code)

### Method 1: Using the VS Code Integrated Terminal (Recommended)
1. Open the project folder in VS Code (`File` > `Open Folder...` > Select `New folder`).
2. Open the built-in terminal: Press <kbd>Ctrl</kbd> + <kbd>`</kbd> (or `Terminal` > `New Terminal`).
3. *(Optional)* Create and activate a virtual environment:
   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```
4. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
5. Run the application:
   ```powershell
   python app.py
   ```
6. Open your web browser and go to: **[http://localhost:5000](http://localhost:5000)**

### Method 2: One-Click Run & Debug (F5)
1. Press <kbd>F5</kbd> on your keyboard (or click **Run and Debug** icon on the left sidebar).
2. Select **Run RentSafe (app.py)**.
3. The server starts in the integrated terminal and opens port `5000`.

---

## 🔑 Pre-Seeded Test Credentials

| Role | Email / Login ID | Password | Portal Features |
| :--- | :--- | :--- | :--- |
| **Admin** | `admin@rentsafe.com` | `admin123` | Generate Lawyer IDs, Configure SMTP, System Overview |
| **Lawyer** | `LAW-2026-7841` *(or `adv.rajesh@rentsafe.com`)* | `lawyer123` | Inspect property deeds, approve/reject listings |
| **Owner** | `owner.vikram@gmail.com` | `owner123` | List flats, upload deeds, chat with matching tenants |
| **Tenant** | `tenant.rohit@gmail.com` | `tenant123` | Filter verified flats, check compatibility, in-app chat |

---

## 📧 Real Email Delivery Setup (SMTP)

To send live OTP emails to real inboxes:
1. Log in as **Admin** (`admin@rentsafe.com` / `admin123`).
2. Scroll to **Real SMTP Mail Delivery Configuration**.
3. Enter your SMTP details (e.g., Gmail with a 16-character Google App Password):
   - **Host**: `smtp.gmail.com`
   - **Port**: `587`
   - **User**: `your.email@gmail.com`
   - **Password**: `your-google-app-password`
   - **TLS**: Enabled
4. Click **Test Verification Email** to verify instant live delivery!
