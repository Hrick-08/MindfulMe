from flask import Flask, render_template, request, redirect, url_for, jsonify, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime,timedelta
import json
import requests
from sqlalchemy import func,text
import statistics
from flask_socketio import SocketIO, emit, join_room, leave_room
import uuid
import random
import smtplib
from email.message import EmailMessage

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///mental_database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
socketio = SocketIO(app, cors_allowed_origins="*")

# Add this context processor after the login_manager setup but before the routes
@app.context_processor
def utility_processor():
    return {
        'can_access_community_chat': can_access_community_chat
    }

# Add these constants after the imports
# OLLAMA_URL = "http://192.168.12.174:11434/api/generate"  # Ollama server URL
# MODEL_NAME = "deepseek-r1:7b"  # Replace with your actual model name if different

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    moods = db.relationship('Mood', backref='user', lazy=True)
    journal_entries = db.relationship('JournalEntry', backref='user', lazy=True)
    messages = db.relationship('ChatMessage', backref='user', lazy=True)

class Mood(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    mood_value = db.Column(db.Integer, nullable=False)  # 1-5 scale
    mood_description = db.Column(db.String(100))
    date = db.Column(db.DateTime, default=datetime.utcnow)

class JournalEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)

class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    resource_type = db.Column(db.String(50), nullable=False)  # article, video, exercise
    url = db.Column(db.String(500))
    tags = db.Column(db.String(200))  # comma-separated tags
    mood_range_min = db.Column(db.Float, default=1.0)  # Minimum mood value this resource is suitable for
    mood_range_max = db.Column(db.Float, default=5.0)  # Maximum mood value this resource is suitable for

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    room = db.Column(db.String(50), default="support")  # Default room is "support"

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Helper function to calculate daily mood average
def calculate_daily_mood_average(user_id, date=None):
    if date is None:
        date = datetime.utcnow()
    
    # Query to get all moods for the user on the specified date
    day_start = datetime(date.year, date.month, date.day, 0, 0, 0)
    day_end = datetime(date.year, date.month, date.day, 23, 59, 59)
    
    daily_moods = Mood.query.filter(
        Mood.user_id == user_id,
        Mood.date >= day_start,
        Mood.date <= day_end
    ).all()
    
    if not daily_moods:
        return None
    
    # Calculate average
    avg_mood = sum(mood.mood_value for mood in daily_moods) / len(daily_moods)
    return avg_mood

# Helper function to get mood category based on average value
def get_mood_category(avg_mood):
    if avg_mood is None:
        return None
    
    if avg_mood < 2.5:
        return {
            "category": "Sad",
            "emoji": "😢",
            "tag": "low_mood"
        }
    elif avg_mood > 3.5:
        return {
            "category": "Happy",
            "emoji": "😊",
            "tag": "positive"
        }
    else:
        return {
            "category": "Neutral",
            "emoji": "😐",
            "tag": "general"
        }

# Helper function to check if user can access community chat
def can_access_community_chat(user_id):
    # Get recent moods (last 3 days)
    three_days_ago = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    three_days_ago = three_days_ago.replace(day=three_days_ago.day - 3)
    
    recent_moods = Mood.query.filter(
        Mood.user_id == user_id,
        Mood.date >= three_days_ago
    ).all()
    
    if not recent_moods:
        return False
    
    # Calculate average mood
    avg_mood = sum(mood.mood_value for mood in recent_moods) / len(recent_moods)
    
    # Allow access if average mood is less than 3
    return avg_mood < 3

# Routes
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template('index.html')

@app.route('/dashboard')
@login_required
def dashboard():
    recent_moods = Mood.query.filter_by(user_id=current_user.id).order_by(Mood.date.desc()).limit(7).all()
    recent_entries = JournalEntry.query.filter_by(user_id=current_user.id).order_by(JournalEntry.date.desc()).limit(3).all()
    
    # Calculate daily mood average
    daily_avg_mood = calculate_daily_mood_average(current_user.id)
    mood_category = get_mood_category(daily_avg_mood)
    
    # Get recommended resources based on mood category
    recommended_resources = get_recommended_resources(current_user.id,limit=3)
    # if mood_category:
    #     recommended_resources = Resource.query.filter(
    #         Resource.tags.like(f'%{mood_category["tag"]}%')
    #     ).limit(3).all()
    
    # Check if user can access community chat
    can_access_chat = can_access_community_chat(current_user.id)
    
    return render_template(
        'dashboard.html', 
        moods=recent_moods, 
        entries=recent_entries,
        daily_avg_mood=daily_avg_mood,
        mood_category=mood_category,
        recommended_resources=recommended_resources,
        can_access_chat=can_access_chat
    )

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        user_exists = User.query.filter_by(username=username).first()
        email_exists = User.query.filter_by(email=email).first()
        
        if user_exists:
            flash('Username already exists')
        elif email_exists:
            flash('Email already exists')
        else:
            hashed_password = generate_password_hash(password)
            new_user = User(username=username, email=email, password=hashed_password)
            db.session.add(new_user)
            db.session.commit()
            login_user(new_user)
            return redirect(url_for('dashboard'))
    
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/chatbot')
@login_required
def chatbot():
    return render_template('chatbot.html')



import os
from dotenv import load_dotenv
from openai import OpenAI
load_dotenv()

# Retrieve API key from .env
api_key = os.getenv("GITHUB_TOKEN")
if not api_key:
    raise ValueError("GitHub token not found. Please set GITHUB_TOKEN in the .env file.")

client = OpenAI(
    base_url="https://models.inference.ai.azure.com",
    api_key=api_key,
)

@app.route('/api/chat', methods=['POST'])
@login_required
def chat():
    user_message = request.form.get('message', '')

    if not user_message:
        return jsonify({"response": "Please enter a message."})

    # System prompt for therapist behavior
    system_message = {
        "role": "system",
        "content": (
            "You are a compassionate therapist specializing in mental health support. "
            "You listen carefully, respond empathetically, and offer thoughtful advice. "
            "Provide coping mechanisms, resources, and emotional support. "
            "Avoid making clinical diagnoses, but encourage seeking professional help when necessary."
        ),
    }

    # User message
    user_message_obj = {"role": "user", "content": user_message}

    try:
        # Generate response using OpenAI
        response = client.chat.completions.create(
            messages=[system_message, user_message_obj],
            model="gpt-4o",
            temperature=0.7,
            max_tokens=4096,
            top_p=1
        )

        ai_response = response.choices[0].message.content
        return jsonify({"response": ai_response})
    except Exception as e:
        return jsonify({"response": f"An error occurred: {str(e)}"})

@app.route('/mood-tracker')
@login_required
def mood_tracker():
    moods = Mood.query.filter_by(user_id=current_user.id).order_by(Mood.date.desc()).all()
    
    # Calculate daily averages for past days
    daily_averages = {}
    
    # Group moods by date
    from collections import defaultdict
    moods_by_date = defaultdict(list)
    
    for mood in moods:
        date_key = mood.date.strftime('%Y-%m-%d')
        moods_by_date[date_key].append(mood)
    
    # Calculate average for each day
    for date_key, day_moods in moods_by_date.items():
        avg = sum(m.mood_value for m in day_moods) / len(day_moods)
        daily_averages[date_key] = {
            'average': avg,
            'category': get_mood_category(avg)
        }
    
    return render_template('mood_tracker.html', moods=moods, daily_averages=daily_averages)


mindfulness_quotes = {
    (1, 2): [
        "This too shall pass. You have survived every bad day so far.",
        "It’s okay to not be okay. Take it one breath at a time.",
        "Even the darkest night will end, and the sun will rise.",
        "You are not alone. You are loved and valued.",
        "Your feelings are valid. Healing takes time.",
        "Small steps are still progress. Keep going.",
        "You are stronger than you think.",
        "Breathe. You are here, and that is enough."
    ],
    (3, 3): [
        "Embrace the present moment. It is all we truly have.",
        "A grateful heart brings joy. Find one thing to appreciate today.",
        "You are enough, just as you are.",
        "Take things as they come. Trust the process.",
        "You are capable of handling whatever comes your way."
    ],
    (4, 5): [
        "Happiness is not something ready-made. It comes from your own actions.",
        "Your positive energy is contagious—share it with the world.",
        "Keep shining. You inspire more people than you know.",
        "Be present, be mindful, be grateful.",
        "Joy is found in the little things. Keep noticing them.",
        "Enjoy this moment—happiness is now.",
        "Life is beautiful, and so are you.",
        "Spread love, kindness, and positivity wherever you go."
    ]
}

def get_mindfulness_quote(mood_value):
        for (low, high), quotes in mindfulness_quotes.items():
            if low <= int(mood_value) <= high:
                return random.choice(quotes)

@app.route('/api/mood', methods=['POST'])
@login_required
def add_mood():
    data = request.json
    mood_value = data.get('value')
    mood_description = data.get('description', '')
    
    new_mood = Mood(
        user_id=current_user.id,
        mood_value=mood_value,
        mood_description=mood_description
    )
    
    db.session.add(new_mood)
    db.session.commit()

    quote = get_mindfulness_quote(mood_value)

    sender_email = "minddful.me@gmail.com"
    receiver_email = current_user.email
    app_password = "msrv uecs uiol vnpd"  # Generate this from your email provider

    msg = EmailMessage()
    msg["Subject"] = "A Mindfulness Quote for You"
    msg["From"] = sender_email
    msg["To"] = receiver_email
    msg.set_content(f"Your Daily Mindfulness Quote: {quote}")  
    msg.add_alternative(f"""\  
    <html>  
    <body style="font-family: Arial, sans-serif; background: linear-gradient(to right, #dfe9f3, #ffffff); padding: 40px; display: flex; justify-content: center;">  
        <div style="max-width: 500px; background: #ffffff; padding: 25px; border-radius: 12px; box-shadow: 0px 6px 12px rgba(0, 0, 0, 0.15); text-align: center;">  
            <h2 style="color: #34495e; margin-bottom: 10px;">🌿 Daily Mindfulness Quote</h2>  
            <p style="font-size: 16px; color: #444; margin-bottom: 10px;">Hello!</p>  
            <p style="font-size: 16px; color: #444; margin-bottom: 15px;">Here's your mindfulness quote for today:</p>  

            <div style="background: #34495e; color: #ffffff; padding: 15px; border-radius: 8px; font-size: 18px; font-weight: bold; box-shadow: 0px 4px 6px rgba(0, 0, 0, 0.1);">  
                {quote}  
            </div>  

            <p style="font-size: 14px; color: #777; margin-top: 15px;">Take a deep breath and embrace the present moment.</p>  
            <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">  
            <p style="font-size: 14px; color: #555;">Stay mindful, stay inspired!</p>  
            <p style="font-size: 14px; font-weight: bold; color: #34495e;">MindfulMe | Wellness Team</p>  
        </div>  
    </body>  
    </html>  
""", subtype='html')

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, app_password)
            server.send_message(msg)
        print("quote sent successfully!")
    except Exception as e:
        print("Error:", e)


        
    return jsonify({"success": True})

@app.route('/journal')
@login_required
def journal():
    entries = JournalEntry.query.filter_by(user_id=current_user.id).order_by(JournalEntry.date.desc()).all()
    # Add the current datetime to the template context
    now = datetime.utcnow()
    return render_template('journal.html', entries=entries, now=now)

@app.route('/api/journal', methods=['POST'])
@login_required
def add_journal():
    data = request.json
    content = data.get('content')
    
    new_entry = JournalEntry(
        user_id=current_user.id,
        content=content
    )
    
    db.session.add(new_entry)
    db.session.commit()
    
    return jsonify({"success": True})

# @app.route('/resources')
# @login_required
# def resources():
#     # Get user's recent moods to personalize recommendations
#     recent_moods = Mood.query.filter_by(user_id=current_user.id).order_by(Mood.date.desc()).limit(5).all()
#     avg_mood = sum([mood.mood_value for mood in recent_moods]) / len(recent_moods) if recent_moods else 3
    
#     # Recommend resources based on mood
#     if avg_mood < 2.5:  # Low mood
#         resources = Resource.query.filter(Resource.tags.like('%low_mood%')).all()
#     elif avg_mood > 3.5:  # High mood
#         resources = Resource.query.filter(Resource.tags.like('%positive%')).all()
#     else:  # Neutral mood
#         resources = Resource.query.filter(Resource.tags.like('%general%')).all()
    
#     return render_template('resources.html', resources=resources)

@app.route('/insights')
@login_required
def insights():
    # Get user's journal entries and moods for analysis
    entries = JournalEntry.query.filter_by(user_id=current_user.id).order_by(JournalEntry.date.desc()).limit(10).all()
    moods = Mood.query.filter_by(user_id=current_user.id).order_by(Mood.date.desc()).limit(30).all()
    
    # Simple analysis (in a real app, you'd use more sophisticated NLP)
    mood_trend = "stable"
    if len(moods) > 7:
        recent_avg = sum([m.mood_value for m in moods[:7]]) / 7
        older_avg = sum([m.mood_value for m in moods[7:14]]) / 7
        if recent_avg > older_avg + 0.5:
            mood_trend = "improving"
        elif recent_avg < older_avg - 0.5:
            mood_trend = "declining"
    
    return render_template('insights.html', entries=entries, moods=moods, mood_trend=mood_trend)

@app.route('/community-chat')
@login_required
def community_chat():
    # Check if user can access the community chat
    if not can_access_community_chat(current_user.id):
        flash('Community chat is only available for users with an average mood score below 3.')
        return redirect(url_for('dashboard'))
    
    # Get recent messages
    recent_messages = ChatMessage.query.filter_by(room="support").order_by(ChatMessage.timestamp.desc()).limit(50).all()
    recent_messages.reverse()  # Show oldest messages first
    
    return render_template('community_chat.html', messages=recent_messages)

# WebSocket event handlers
@socketio.on('connect')
def handle_connect():
    if not current_user.is_authenticated:
        return False
    
    # Check if user can access the community chat
    if not can_access_community_chat(current_user.id):
        return False
    
    # Join the support room
    join_room("support")
    
    # Notify others that a new user has joined
    emit('status', {
        'username': current_user.username,
        'message': ' has joined the chat',
        'timestamp': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    }, room="support")

@socketio.on('disconnect')
def handle_disconnect():
    if current_user.is_authenticated:
        # Leave the support room
        leave_room("support")
        
        # Notify others that a user has left
        emit('status', {
            'username': current_user.username,
            'message': ' has left the chat',
            'timestamp': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        }, room="support")

@socketio.on('message')
def handle_message(data):
    if not current_user.is_authenticated:
        return
    
    # Check if user can access the community chat
    if not can_access_community_chat(current_user.id):
        return
    
    content = data.get('message', '').strip()
    if not content:
        return
    
    # Save message to database
    new_message = ChatMessage(
        user_id=current_user.id,
        content=content,
        room="support"
    )
    db.session.add(new_message)
    db.session.commit()
    
    # Broadcast message to all users in the room
    emit('message', {
        'id': new_message.id,
        'username': current_user.username,
        'message': content,
        'timestamp': new_message.timestamp.strftime('%Y-%m-%d %H:%M:%S')
    }, room="support")


def get_recommended_resources(user_id, limit=6):
    """Get personalized resource recommendations based on user's mood"""
    avg_mood = get_user_mood_average(user_id)
    
    # Query resources that match the user's mood range
    resources = Resource.query.filter(
        Resource.mood_range_min <= avg_mood,
        Resource.mood_range_max >= avg_mood
    ).limit(limit).all()
    
    # If not enough resources found, get general resources
    if len(resources) < limit:
        additional_resources = Resource.query.filter(
            ~Resource.id.in_([r.id for r in resources]) if resources else True
        ).limit(limit - len(resources)).all()
        resources.extend(additional_resources)
    
    return resources

def get_user_mood_average(user_id, days=7):
    """Get the average mood for a user over the specified number of days"""
    end_date = datetime.utcnow().date()
    start_date = end_date - timedelta(days=days)
    
    # Get all moods for the user in the date range
    moods = Mood.query.filter(
        Mood.user_id == user_id,
        Mood.date >= datetime.combine(start_date, datetime.min.time()),
        Mood.date <= datetime.combine(end_date, datetime.max.time())
    ).all()
    
    if moods:
        mood_values = [mood.mood_value for mood in moods]
        return statistics.mean(mood_values)
    
    return 3.0  # Default to neutral mood if no data

@app.route('/resources')
@login_required
def resources():
    # Get user's average mood to personalize recommendations
    avg_mood = get_user_mood_average(current_user.id)
    
    # Get all resources for display
    all_resources = Resource.query.all()
    
    # Get user's recent moods to personalize recommendations
    recent_moods = Mood.query.filter_by(user_id=current_user.id).order_by(Mood.date.desc()).limit(5).all()
    avg_mood = sum([mood.mood_value for mood in recent_moods]) / len(recent_moods) if recent_moods else 3
    
    # Recommend resources based on mood
    if avg_mood < 2.5:  # Low mood
        resources = Resource.query.filter(Resource.tags.like('%low_mood%')).all()
    elif avg_mood > 3.5:  # High mood
        resources = Resource.query.filter(Resource.tags.like('%positive%')).all()
    else:  # Neutral mood
        resources = Resource.query.filter(Resource.tags.like('%general%')).all()
    
    # return render_template('resources.html', resources=resources)
    # Get personalized recommendations
    recommended_resources = get_recommended_resources(current_user.id)
    
    return render_template(
        'resources.html', 
        resources=all_resources,
        recommended_resources=recommended_resources,
        avg_mood=avg_mood,
        # mood_description=get_mood_description(avg_mood)
        )


@app.route('/admin/resources/edit/<int:resource_id>', methods=['GET', 'POST'])
@login_required
def edit_resource(resource_id):
    if current_user.id != 1:  # Admin check
        flash("Access denied")
        return redirect(url_for('admin_resources'))

    resource = Resource.query.get_or_404(resource_id)

    if request.method == 'POST':
        resource.title = request.form['title']
        resource.description = request.form['description']
        resource.resource_type = request.form['resource_type']
        resource.url = request.form['url']
        resource.tags = request.form['tags']
        resource.mood_range_min = float(request.form['mood_range_min'])
        resource.mood_range_max = float(request.form['mood_range_max'])

        db.session.commit()
        flash("Resource updated successfully!")
        return redirect(url_for('admin_resources'))

    return render_template('edit_resource.html', resource=resource)

@app.route('/admin/resources/delete/<int:resource_id>', methods=['POST'])
@login_required
def delete_resource(resource_id):
    if current_user.id != 1:
        flash("Access denied")
        return redirect(url_for('admin_resources'))

    resource = Resource.query.get_or_404(resource_id)
    db.session.delete(resource)
    db.session.commit()
    flash("Resource deleted successfully!")

    return redirect(url_for('admin_resources'))


@app.route('/admin/resources', methods=['GET', 'POST'])
@login_required
def admin_resources():
    # Simple admin check - in a real app, you'd have proper admin roles
    if current_user.id != 1:  # Assuming user with ID 1 is admin
        flash('Access denied')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        title = request.form.get('title')
        description = request.form.get('description')
        resource_type = request.form.get('resource_type')
        url = request.form.get('url')
        tags = request.form.get('tags')
        mood_range_min = float(request.form.get('mood_range_min', 1.0))
        mood_range_max = float(request.form.get('mood_range_max', 5.0))
        
        new_resource = Resource(
            title=title,
            description=description,
            resource_type=resource_type,
            url=url,
            tags=tags,
            mood_range_min=mood_range_min,
            mood_range_max=mood_range_max
        )
        
        db.session.add(new_resource)
        db.session.commit()
        
        flash('Resource added successfully')
        return redirect(url_for('admin_resources'))
    
    resources = Resource.query.all()
    return render_template('admin_resources.html', resources=resources)


def init_app():
    with app.app_context():
        # Create all tables
        db.create_all()
        
        # Check if tables were created successfully
        try:
            db.session.execute(text("SELECT 1 FROM resource LIMIT 1"))
            print("Resource table exists!")
        except Exception as e:
            print(f"Resource table check: {str(e)}")

        if Resource.query.count() == 0:
            default_resources = [
                # Existing resources with updated URLs for exercise types
                Resource(
                    title="Understanding Depression",
                    description="An informative article about depression symptoms and coping strategies.",
                    resource_type="article",
                    url="https://www.nimh.nih.gov/health/topics/depression",
                    tags="depression,low_mood,mental_health",
                    mood_range_min=1.0,
                    mood_range_max=2.5
                ),
                Resource(
                    title="5-Minute Mood Boosting Meditation",
                    description="A short guided meditation to help lift your mood.",
                    resource_type="video",
                    url="https://www.youtube.com/watch?v=jHBtXsKt7xs",
                    tags="meditation,low_mood,quick",
                    mood_range_min=1.0,
                    mood_range_max=2.5
                ),
                Resource(
                    title="Gratitude Exercise",
                    description="A simple exercise to practice gratitude even during difficult times.",
                    resource_type="exercise",
                    url="https://www.therapistaid.com/therapy-worksheet/gratitude-exercises",
                    tags="gratitude,low_mood,exercise",
                    mood_range_min=1.0,
                    mood_range_max=3.0
                ),
                Resource(
                    title="Mindfulness in Daily Life",
                    description="Learn how to incorporate mindfulness into your everyday activities.",
                    resource_type="article",
                    url="https://www.mindful.org/how-to-practice-mindfulness",
                    tags="mindfulness,general,mental_health",
                    mood_range_min=2.5,
                    mood_range_max=3.5
                ),
                Resource(
                    title="Progressive Muscle Relaxation",
                    description="A guided exercise to release tension in your body.",
                    resource_type="video",
                    url="https://www.youtube.com/watch?v=Z21Xslddz3Y",
                    tags="relaxation,stress,general",
                    mood_range_min=2.0,
                    mood_range_max=4.0
                ),
                Resource(
                    title="Daily Reflection Journal Prompts",
                    description="Prompts to help you reflect on your day and set intentions.",
                    resource_type="exercise",
                    url="https://positivepsychology.com/journaling-prompts/",
                    tags="journaling,reflection,general",
                    mood_range_min=2.0,
                    mood_range_max=4.0
                ),
                Resource(
                    title="Maintaining Positive Mental Health",
                    description="Strategies to maintain and build upon positive mental health.",
                    resource_type="article",
                    url="https://www.mentalhealth.org.uk/a-to-z/p/positive-mental-health",
                    tags="positive,mental_health,wellbeing",
                    mood_range_min=3.5,
                    mood_range_max=5.0
                ),
                Resource(
                    title="Joyful Movement Exercise",
                    description="A fun workout that celebrates feeling good in your body.",
                    resource_type="video",
                    url="https://www.youtube.com/watch?v=-ZOCVNIIz3M",
                    tags="exercise,joy,positive",
                    mood_range_min=3.5,
                    mood_range_max=5.0
                ),
                Resource(
                    title="Strength-Building Reflection",
                    description="An exercise to identify and build upon your personal strengths.",
                    resource_type="exercise",
                    url="https://positivepsychology.com/strengths-based-interventions/",
                    tags="strengths,positive,growth",
                    mood_range_min=3.0,
                    mood_range_max=5.0
                )
            ]

            for resource in default_resources:
                db.session.add(resource)
            
            db.session.commit()


if __name__ == '__main__':
    init_app()
    with app.app_context():
        db.create_all()
    socketio.run(app, debug=True)


