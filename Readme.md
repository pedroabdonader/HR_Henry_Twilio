Here's the content formatted as a Markdown (.md) file:

markdown
# HR Henry - AI Voice Assistant

## Overview

HR Henry is an intelligent HR assistant designed to assist employees with various HR-related tasks in a friendly and efficient manner. Built using FastAPI, Twilio, and OpenAI's GPT-4, HR Henry can handle inquiries related to payroll, leave requests, benefits, and more, all through voice interactions.

## Features

- **Voice Interaction**: Connects with users via Twilio's voice services.
- **Real-time Processing**: Utilizes OpenAI's real-time API for dynamic responses.
- **Email Notifications**: Sends email confirmations for leave requests and other HR-related communications.
- **HR Policies**: Provides information on company policies regarding leave, harassment, and benefits.

## Requirements

- Python 3.7 or higher
- FastAPI
- Twilio
- OpenAI API
- dotenv
- websockets
- smtplib

## Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/yourusername/hr-henry.git
   cd hr-henry


Create a virtual environment and activate it:

bash
python -m venv venv
source venv/bin/activate  # On Windows use `venv\Scripts\activate`


Install the required packages:

bash
pip install -r requirements.txt


Create a

.env
file in the root directory and add the following environment variables:

plaintext
OPENAI_API_KEY=your_openai_api_key
SENDER_EMAIL=your_email@example.com
RECEIVER_EMAIL1=receiver1@example.com
RECEIVER_EMAIL2=receiver2@example.com
RECEIVER_EMAIL3=receiver3@example.com
GMAIL_APP_PASSWORD=your_gmail_app_password
PORT=5050  # Optional, defaults to 5050

Running the Application

To start the application, run:

bash
uvicorn main:app --host 0.0.0.0 --port 5050


You can access the API at

http://localhost:5050
.

API Endpoints
GET /: Returns a message indicating that the Twilio Media Stream Server is running.
POST /incoming-call: Handles incoming calls and connects to the media stream.
WebSocket /media-stream: Manages WebSocket connections for real-time audio processing.
Usage

Once the application is running, you can initiate a call to the Twilio number associated with your account. HR Henry will greet the user and assist with HR-related inquiries.

Example Interaction
User: "Hi, I’d like to inquire about my current leave balance."
HR Henry: "Sure! You have a remaining leave balance of 16 days."
Email Notifications

HR Henry can send email notifications for leave requests. The email will include a confirmation message with the details of the request.

Example Email

Subject: Time Off Request Confirmation

Body:

html
<p>Hi there,</p>
<p>Thank you for your request for time off on <strong>August 26</strong>. I have submitted your request for Paid Time Off (PTO) to your manager for approval.</p>
<p>Please note that your manager will review the request, and you will be notified once a decision has been made. If you have any further questions or need assistance with anything else, feel free to reach out!</p>
<p>Best regards,<br>HR Henry</p>

Contributing

Contributions are welcome! Please feel free to submit a pull request or open an issue for any enhancements or bug fixes.

License

This project is licensed under the MIT License. See the LICENSE file for more details.

For any questions or support, please contact the project maintainer. Enjoy using HR Henry!

