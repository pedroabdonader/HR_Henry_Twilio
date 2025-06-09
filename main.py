import os
import json
import base64
import asyncio
import websockets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect, Say, Stream
from dotenv import load_dotenv

load_dotenv()

# Configuration
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
PORT = int(os.getenv('PORT', 5050))

# System Messages for Different Agents
SYSTEM_MESSAGE_ORCHESTRATION = (
"""
You are an orchestration agent. Your role is to manage interactions between different agents and ensure smooth communication. You should assist in directing queries to the appropriate agent based on user input.
"""
)

SYSTEM_MESSAGE_HR = (
"""
You are an intelligent HR assistant. Your role is to assist employees with various HR-related tasks in a friendly and efficient manner, focusing solely on HR-specific topics.
"""
)

SYSTEM_MESSAGE_PAYROLL = (
"""
You are a Payroll agent. Your role is to assist employees with payroll-related inquiries, including paychecks, deductions, and payroll schedules.
"""
)

SYSTEM_MESSAGE_BENEFITS = (
"""
You are a Benefits agent. Your role is to assist employees with benefits-related inquiries, including health insurance, retirement plans, and other employee benefits.
"""
)

SYSTEM_MESSAGE_LEAVE = (
"""
You are a Leave Policies agent. Your role is to assist employees with inquiries related to leave policies, including vacation, sick leave, and other types of leave.
"""
)

# Voices for Different Agents
VOICE_ORCHESTRATION = 'jane'
VOICE_HR = 'ash'
VOICE_PAYROLL = 'mike'
VOICE_BENEFITS = 'susan'
VOICE_LEAVE = 'lisa'

LOG_EVENT_TYPES = [
    'error', 'response.content.done', 'rate_limits.updated',
    'response.done', 'input_audio_buffer.committed',
    'input_audio_buffer.speech_stopped', 'input_audio_buffer.speech_started',
    'session.created'
]
SHOW_TIMING_MATH = False

app = FastAPI()

# Initialize a global variable to hold the conversation state
conversation_state = {
    "current_step": None,
    "summary": ""
}

# List of keywords to trigger email sending
email_keywords = ["send", "email", "summary", "send an email"]
no_change_keywords = ["no", "not", "don't", "no changes", "skip"]

# List of keywords for different agents
payroll_keywords = ["payroll", "salary", "wages", "paycheck", "deductions", "overtime"]
benefits_keywords = ["benefits", "insurance", "health", "retirement", "401k", "vacation"]
leave_keywords = ["leave", "vacation", "sick", "holiday", "time off", "absence"]

## Function calling functions:
def send_email(subject, body):
    print("Sending email with subject:", subject)
    # Email configuration
    sender_email = os.environ.get('SENDER_EMAIL')
    receiver_email = f"{os.environ.get('RECEIVER_EMAIL1')}, {os.environ.get('RECEIVER_EMAIL2')}, {os.environ.get('RECEIVER_EMAIL3')}, j33@gmail.com"
    password = os.environ.get('GMAIL_APP_PASSWORD')  # Use your app password here

    if not body:
        body = """
        <html>
        <body>
            <h1>This is a test email</h1>
            <p>This email is sent from Python with <strong>HTML formatting</strong>!</p>
        </body>
        </html>
        """

    # Create the email
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'html'))

    # Send the email
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()  # Upgrade the connection to a secure encrypted SSL/TLS connection
            server.login(sender_email, password)
            server.send_message(msg)
        return str({"status": "success", "message": "Please allow some time for the email to arrive"})
    except Exception as e:
        return f"Failed to send email: {e}"

# Function to call the appropriate function based on the name
def call_function(name, args):
    if name == "send_email":  # Check if the function is send_email
        return send_email(**args)  # Call send_email with the provided arguments
    else:
        raise ValueError(f"Unknown function: {name}")  # Raise an error for unknown functions

# Define tools
tools = [{
    "type": "function",
    "name": "send_email",
    "description": "Send an email to the user with a subject and body.",
    "parameters": {
        "type": "object",
        "properties": {
            "subject": {"type": "string","description": "The subject of the email."},
            "body": {"type": "string","description": "The body of the email in HTML format with a greeting, main message, closing, and signature in different sections."}
        },
        "required": ["subject","body"],
        "additionalProperties": False  # No additional properties allowed
    }
}]

if not OPENAI_API_KEY:
    raise ValueError('Missing the OpenAI API key. Please set it in the .env file.')

@app.get("/", response_class=JSONResponse)
async def index_page():
    return {"message": "Twilio Media Stream Server is running!"}

@app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    """Handle incoming call and return TwiML response to connect to Media Stream."""
    response = VoiceResponse()
    response.say("Please wait while we connect your call to the AI voice assistant.")
    response.pause(length=1)
    host = request.url.hostname
    connect = Connect()
    connect.stream(url=f'wss://{host}/media-stream')
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")

@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    """Handle WebSocket connections between Twilio and OpenAI."""
    print("Client connected")
    await websocket.accept()

    async with websockets.connect(
        'wss://api.openai.com/v1/realtime?model=gpt-4o-mini-realtime-preview',
        extra_headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=v1"
        }
    ) as openai_ws:
        await initialize_session(openai_ws)

        # Connection specific state
        stream_sid = None
        latest_media_timestamp = 0
        last_assistant_item = None
        mark_queue = []
        response_start_timestamp_twilio = None
        
        async def receive_from_twilio():
            """Receive audio data from Twilio and send it to the OpenAI Realtime API."""
            nonlocal stream_sid, latest_media_timestamp
            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)
                    if data['event'] == 'media' and openai_ws.open:
                        latest_media_timestamp = int(data['media']['timestamp'])
                        audio_append = {
                            "type": "input_audio_buffer.append",
                            "audio": data['media']['payload']
                        }
                        await openai_ws.send(json.dumps(audio_append))
                    elif data['event'] == 'start':
                        stream_sid = data['start']['streamSid']
                        print(f"Incoming stream has started {stream_sid}")
                        response_start_timestamp_twilio = None
                        latest_media_timestamp = 0
                        last_assistant_item = None
                    elif data['event'] == 'mark':
                        if mark_queue:
                            mark_queue.pop(0)
            except WebSocketDisconnect:
                print("Client disconnected.")
                if openai_ws.open:
                    await openai_ws.close()

        async def send_to_twilio():
            """Receive events from the OpenAI Realtime API, send audio back to Twilio."""
            nonlocal stream_sid, last_assistant_item, response_start_timestamp_twilio
            try:
                async for openai_message in openai_ws:
                    response = json.loads(openai_message)
                    if response['type'] in LOG_EVENT_TYPES:
                        print(f"Received event: {response['type']}", response)

                    # Check for function call response in the output array
                    if response.get('type') == 'response.done' and 'output' in response['response']:
                        for item in response['response']['output']:
                            if item['type'] == 'function_call':
                                function_call = item
                                args = json.loads(function_call['arguments'])
                                print(f"Calling function: {function_call['name']} with args: {args}")

                                # Call the function and handle the response
                                try:
                                    await openai_ws.send(json.dumps({"type": "response.create"}))
                                    result = call_function(function_call['name'], args)
                                    
                                    # Create the output as a JSON string
                                    output = json.dumps({"message": result})  # Adjust this based on what your function returns

                                    # Send the result back to OpenAI as a function call output
                                    await openai_ws.send(json.dumps({
                                        "type": "conversation.item.create",
                                        "item": {
                                            "type": "function_call_output",
                                            "call_id": function_call['call_id'],  # Use the call_id from the function call
                                            "output": output  # Send the result back as a JSON string
                                        }
                                    }))
                                    await openai_ws.send(json.dumps({"type": "response.create"}))

                                    # Update the conversation summary
                                    conversation_state["summary"] += f"{result}\n"  # Append the result to the summary

                                except Exception as e:
                                    print(f"Error calling function: {e}")
                                    await openai_ws.send(json.dumps({
                                        "type": "response.cancel",  # Use a valid type for error responses
                                        "error": str(e)
                                    }))
                                    continue

                    if response.get('type') == 'response.audio.delta' and 'delta' in response:
                        audio_payload = base64.b64encode(base64.b64decode(response['delta'])).decode('utf-8')
                        audio_delta = {
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {
                                "payload": audio_payload
                            }
                        }
                        await websocket.send_json(audio_delta)

                        if response_start_timestamp_twilio is None:
                            response_start_timestamp_twilio = latest_media_timestamp

                        # Update last_assistant_item safely
                        if response.get('item_id'):
                            last_assistant_item = response['item_id']

                        await send_mark(websocket, stream_sid)

                    if response.get('type') == 'input_audio_buffer.speech_started':
                        print("Speech started detected.")
                        if last_assistant_item:
                            print(f"Interrupting response with id: {last_assistant_item}")
                            await handle_speech_started_event()
            except Exception as e:
                print(f"Error in send_to_twilio: {e}")

        async def handle_speech_started_event():
            """Handle interruption when the caller's speech starts."""
            nonlocal response_start_timestamp_twilio, last_assistant_item
            print("Handling speech started event.")
            if mark_queue and response_start_timestamp_twilio is not None:
                elapsed_time = latest_media_timestamp - response_start_timestamp_twilio
                if last_assistant_item:
                    truncate_event = {
                        "type": "conversation.item.truncate",
                        "item_id": last_assistant_item,
                        "content_index": 0,
                        "audio_end_ms": elapsed_time
                    }
                    await openai_ws.send(json.dumps(truncate_event))

                await websocket.send_json({
                    "event": "clear",
                    "streamSid": stream_sid
                })

                mark_queue.clear()
                last_assistant_item = None
                response_start_timestamp_twilio = None

        async def send_mark(connection, stream_sid):
            if stream_sid:
                mark_event = {
                    "event": "mark",
                    "streamSid": stream_sid,
                    "mark": {"name": "responsePart"}
                }
                await connection.send_json(mark_event)
                mark_queue.append('responsePart')

        await asyncio.gather(receive_from_twilio(), send_to_twilio())

async def send_initial_conversation_item(openai_ws, agent_type):
    """Send initial conversation item if AI talks first."""
    if agent_type == "Orchestration":
        initial_conversation_item = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Hello! I am the orchestration agent, here to assist you with managing your requests. A summary of this call will be sent to your email."
                    }
                ]
            }
        }
    elif agent_type == "HR":
        initial_conversation_item = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Hello there! I am HR, your AI voice assistant! I can help you with anything HR related such as Payroll, Benefits, and Leave policies! A summary of this call will be sent to your email."
                    }
                ]
            }
        }
    elif agent_type == "Payroll":
        initial_conversation_item = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Hello! I am the Payroll agent, ready to assist you with payroll-related inquiries. A summary of this call will be sent to your email."
                    }
                ]
            }
        }
    elif agent_type == "Benefits":
        initial_conversation_item = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Hello! I am the Benefits agent, here to help you with your benefits-related questions. A summary of this call will be sent to your email."
                    }
                ]
            }
        }
    elif agent_type == "Leave":
        initial_conversation_item = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Hello! I am the Leave Policies agent, ready to assist you with your leave inquiries. A summary of this call will be sent to your email."
                    }
                ]
            }
        }
    
    await openai_ws.send(json.dumps(initial_conversation_item))
    await openai_ws.send(json.dumps({"type": "response.create"}))

async def initialize_session(openai_ws):
    """Control initial session with OpenAI."""
    session_update = {
        "type": "session.update",
        "session": {
            "turn_detection": {"type": "server_vad",
                               "threshold": 0.7,
                               "silence_duration_ms": 600},
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "voice": VOICE_ORCHESTRATION,  # Default voice for orchestration agent
            "instructions": SYSTEM_MESSAGE_ORCHESTRATION,
            "modalities": ["text", "audio"],
            "temperature": 0.8,
            "tools": tools,
            "tool_choice": "auto"
        }
    }
    print('Sending session update:', json.dumps(session_update))
    await openai_ws.send(json.dumps(session_update))

    # Uncomment the next line to have the AI speak first
    await send_initial_conversation_item(openai_ws, "Orchestration")

async def route_to_agent(user_input, openai_ws):
    """Route user input to the appropriate agent based on keywords."""
    user_input_lower = user_input.lower()
    
    if any(keyword in user_input_lower for keyword in payroll_keywords):
        await send_initial_conversation_item(openai_ws, "Payroll")
        return VOICE_PAYROLL, SYSTEM_MESSAGE_PAYROLL
    elif any(keyword in user_input_lower for keyword in benefits_keywords):
        await send_initial_conversation_item(openai_ws, "Benefits")
        return VOICE_BENEFITS, SYSTEM_MESSAGE_BENEFITS
    elif any(keyword in user_input_lower for keyword in leave_keywords):
        await send_initial_conversation_item(openai_ws, "Leave")
        return VOICE_LEAVE, SYSTEM_MESSAGE_LEAVE
    else:
        await send_initial_conversation_item(openai_ws, "HR")
        return VOICE_HR, SYSTEM_MESSAGE_HR

async def wait_for_user_input(openai_ws, prompt, initial_timeout=5, extension_timeout=2):
    """Wait for user input based on the provided prompt with a dynamic timeout."""
    global conversation_state

    # Set the current step to the prompt being asked
    conversation_state["current_step"] = prompt

    # Send the prompt to the user
    await openai_ws.send(json.dumps({
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "input_text",
                    "text": prompt
                }
            ]
        }
    }))

    user_input = ""
    listening = True
    timeout_counter = 0

    while listening:
        # Start listening for user input
        user_input_task = asyncio.create_task(receive_user_response(openai_ws))

        # Wait for user input or timeout
        try:
            await asyncio.wait_for(user_input_task, timeout=initial_timeout)
            user_input += user_input_task.result() + " "  # Append user input
            timeout_counter = 0  # Reset timeout counter after receiving input

            # Check if the user continues speaking
            while True:
                await asyncio.sleep(extension_timeout)  # Wait for a short period
                if user_input_task.done():
                    break  # Exit if user input task is complete

                # Check if the user has stopped speaking
                if not user_input_task.done() and timeout_counter < 3:  # Allow 3 extensions
                    timeout_counter += 1
                    await asyncio.sleep(extension_timeout)  # Wait for more input
                else:
                    listening = False  # Stop listening if no input is detected
                    break

        except asyncio.TimeoutError:
            listening = False  # Stop listening if timeout occurs

    return user_input.strip() if user_input else None

async def receive_user_response(openai_ws):
    """Receive the user's response from the WebSocket."""
    user_input = ""
    try:
        async for message in openai_ws:
            response = json.loads(message)
            if response.get('type') == 'user_input':
                user_input += response['content'] + " "  # Append user input
                return user_input.strip()  # Return the complete user input
    except Exception as e:
        print(f"Error receiving user response: {e}")
    return None  # Return None if no input was received

async def handle_user_input(user_input, openai_ws):
    """Handle user input and route to the appropriate agent."""
    voice, system_message = await route_to_agent(user_input, openai_ws)

    # Check if the user wants to send an email based on keywords
    if any(keyword in user_input.lower() for keyword in email_keywords):
        # Inform the user that a summary will be sent
        await openai_ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "input_text",
                        "text": "A summary of our conversation will be sent to your email. What subject would you like for the email?"
                    }
                ]
            }
        }))
        
        # Capture the subject
        subject = await wait_for_user_input(openai_ws, "What subject would you like for the email?")
        
        # Present the summary to the user
        await openai_ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "input_text",
                        "text": f"Here is the summary of our conversation:\n{conversation_state['summary']}\nWould you like to change anything or add more details?"
                    }
                ]
            }
        }))
        
        # Capture any changes or additions to the summary
        additional_info = await wait_for_user_input(openai_ws, "Would you like to add anything to the summary?")
        
        # Check if the user does not want to make changes
        if any(keyword in additional_info.lower() for keyword in no_change_keywords):
            # Send the email immediately without waiting for further input
            final_summary = conversation_state['summary']
            result = send_email(subject, final_summary)
            await openai_ws.send(json.dumps({
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "input_text",
                            "text": result  # Send the result of the email sending process
                        }
                    ]
                }
            }))
            return

        # Finalize the summary
        final_summary = f"{conversation_state['summary']}\nAdditional Notes: {additional_info}" if additional_info else conversation_state['summary']
        
        # Send the email
        result = send_email(subject, final_summary)
        await openai_ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "input_text",
                        "text": result  # Send the result of the email sending process
                    }
                ]
            }
        }))
        return

    # Update the session with the new agent's voice and system message
    session_update = {
        "type": "session.update",
        "session": {
            "voice": voice,
            "instructions": system_message,
        }
    }
    await openai_ws.send(json.dumps(session_update))

# Update the receive_user_response function to call handle_user_input
async def receive_user_response(openai_ws):
    """Receive the user's response from the WebSocket."""
    user_input = ""
    try:
        async for message in openai_ws:
            response = json.loads(message)
            if response.get('type') == 'user_input':
                user_input += response['content'] + " "  # Append user input
                user_input = user_input.strip()  # Clean up the input
                if user_input:  # If there is user input, handle it
                    await handle_user_input(user_input, openai_ws)
                return user_input  # Return the complete user input
    except Exception as e:
        print(f"Error receiving user response: {e}")
    return None  # Return None if no input was received

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
