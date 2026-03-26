from gevent import monkey
monkey.patch_all()
from fileinput import filename
from flask import Flask, render_template, request, redirect, session, flash, url_for, send_from_directory, Response
from models import db, User, Material, Classroom, Submission, Notification, enrollment_table
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask import flash
from flask import session, request
from flask_mail import Mail, Message
from flask_socketio import SocketIO, emit, join_room, leave_room
import os
import random                         # <--- ADDED
import string

app = Flask(__name__)

# 1. SETUP CONFIGURATIONS
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///portal.db'
with app.app_context():
    # This creates the tables/columns if they don't exist
    db.create_all()
# We changed this from 'uploads' to 'static/uploads'
app.config['UPLOAD_FOLDER'] = 'static/uploads' 
app.secret_key = "super_secret_key"

# --- EMAIL CONFIGURATION (Keeping all your hard work here!) ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('EMAIL_USER')
app.config['MAIL_PASSWORD'] = os.environ.get('EMAIL_PASS')

mail = Mail(app)

os.makedirs('static/uploads/materials', exist_ok=True)
os.makedirs('static/uploads/assignments', exist_ok=True)
os.makedirs('static/uploads/snapshots', exist_ok=True) # Add this for your Gallery!

db.init_app(app)
with app.app_context():
    db.create_all()


# After app.config settings
socketio = SocketIO(app, cors_allowed_origins="*")

# A simple test to see if a student joined the "Classroom"
@socketio.on('join-room')
def handle_join_room(data):
    room_id = data.get('room', 'main_classroom')
    join_room(room_id)
    
    # 1. Get the name (check data first, then session)
    user_name_to_send = data.get('username') or session.get('username') or "Student"
    
    # 2. Update session so chat stays fixed
    session['username'] = user_name_to_send
    session['room'] = room_id
    session['role'] = data.get('role', 'student')

    # 3. FIX: Send the name explicitly in the emit
    # This is what the video tile uses to replace "undefined"
    emit('user-connected', {
        'id': request.sid, 
        'username': user_name_to_send, 
        'role': session['role']
    }, to=room_id, include_self=False)

    print(f"DEBUG: {user_name_to_send} joined {room_id}")

@socketio.on('signal')
def handle_signal(data):
    # Include the sender's username from the session in the signal packet
    emit('signal', {
        'from': request.sid,
        'username': session.get('username'), # Add this line
        'role': session.get('role'),         # Add this line
        'signal': data['signal']
    }, to=data['to'])

@socketio.on('chat_message')
def handle_chat_message(data):
    # Get info from the session we saved in join-room
    user = session.get('username', 'Guest') 
    room = session.get('room')
    
    emit('new_message', {
        'user': user,
        'msg': data.get('msg')
    }, to=room)

@socketio.on('moderator-action')
def handle_mod_action(data):
    """Allows the teacher to mute or request unmute from students"""
    # SECURITY: Only allow if the sender is actually a teacher
    if session.get('role') == 'teacher':
        # We use 'to=' or 'room=' (they do the same thing)
        # We pass the 'action' which will now be 'mute' OR 'unmute_request'
        emit('mod-command', {'action': data['action']}, to=data['target'])

@socketio.on('disconnect')
def handle_disconnect():
    """Cleanup when someone leaves"""
    emit('user-disconnected', request.sid, broadcast=True)
    

# 3. THE ROUTES
@app.route('/')
def home():
    if 'username' not in session:
        return redirect('/login')
    user = User.query.filter_by(username=session['username']).first()
    if not user:
        session.clear() 
        return redirect('/login')

    all_classrooms = Classroom.query.all()
    # Fetch all users so the teacher can see who requested a reset
    all_users = User.query.all() 
    notifications = Notification.query.filter_by(user_id=user.id, is_read=False).order_by(Notification.timestamp.desc()).all()

    if user.role == 'teacher':
        display_materials = Material.query.all()
        pending_requests = db.session.query(User, Classroom).\
            select_from(User).\
            join(enrollment_table, User.id == enrollment_table.c.user_id).\
            join(Classroom, Classroom.id == enrollment_table.c.classroom_id).\
            filter(enrollment_table.c.status == 'pending').all()
        submissions = Submission.query.all()
    else:
        approved_ids = [r[0] for r in db.session.query(enrollment_table.c.classroom_id).filter(
            (enrollment_table.c.user_id == user.id) & (enrollment_table.c.status == 'approved')).all()]
        display_materials = Material.query.filter(Material.class_id.in_(approved_ids)).all()
        pending_requests = []
        submissions = Submission.query.filter_by(student_id=user.id).all()

    return render_template('dashboard.html', 
                           username=user.username, 
                           role=user.role, 
                           classrooms=all_classrooms, 
                           all_users=all_users, # Added this line
                           materials=display_materials, 
                           pending_requests=pending_requests,
                           notifications=notifications,
                           submissions=submissions)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identifier = request.form.get('username') # The input field
        password = request.form.get('password')
        
        # Check if 'identifier' matches username OR email column in your DB
        user = User.query.filter((User.username == identifier) | (User.email == identifier)).first()
        
        if user and check_password_hash(user.password, password):
            session['username'] = user.username
            session['role'] = user.role
            return redirect('/')
        
        flash('Invalid username/email or password', 'error')
    return render_template('login.html')

@app.route('/change_password', methods=['POST'])
def change_password():
    if 'username' not in session:
        return redirect('/login')
        
    user = User.query.filter_by(username=session['username']).first()
    old_pw = request.form.get('old_password')
    new_pw = request.form.get('new_password')
    
    # 1. Verify the old password matches the hash in the DB
    if user and check_password_hash(user.password, old_pw):
        # 2. Hash the new password and update
        user.password = generate_password_hash(new_pw, method='pbkdf2:sha256')
        
        # 3. Add the notification you requested
        db.session.add(Notification(
            user_id=user.id, 
            message="Your password was successfully changed."
        ))
        
        db.session.commit()
        return redirect('/')
    else:
        # You could add an error message here later
        return redirect('/')

# Define your secret teacher key here
TEACHER_ACCESS_KEY = "OurviewStaff3006!" 

@app.route('/register', methods=['GET', 'POST']) # 1. Added 'GET' here
def register():
    # 2. Check if the user is SUBMITTING the form
    if request.method == 'POST':
        role = request.form.get('role')
        username = request.form.get('username')
        password = request.form.get('password')
        
        # SECURITY CHECK
        if role == 'teacher':
            user_code = request.form.get('teacher_code')
            if user_code != TEACHER_ACCESS_KEY:
                flash("❌ Access Denied: Incorrect Teacher Code.", "danger")
                return redirect(url_for('register'))

        # Proceed with registration
        hashed_password = generate_password_hash(password)
        new_user = User(username=username, password=hashed_password, role=role)
        
        db.session.add(new_user)
        db.session.commit()
        flash("Account created successfully!", "success")
        return redirect(url_for('login'))

    # 3. If the user is just ARRIVING at the page (GET), show them the form
    return render_template('register.html')

@app.route('/request_reset', methods=['POST'])
def request_reset():
    identifier = request.form.get('username')
    user = User.query.filter((User.username == identifier) | (User.email == identifier)).first()
    
    if user:
        import random, string
        temp_pass = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        user.password = generate_password_hash(temp_pass, method='pbkdf2:sha256')
        user.reset_requested = True
        
        target_email = user.email if user.email else identifier
        if "@" not in target_email:
            target_email = f"{target_email}@gmail.com"

        try:
            msg = Message("Temporary Password - School Portal", 
                          sender=app.config['MAIL_USERNAME'], 
                          recipients=[target_email])
            msg.body = f"Hello {user.username},\n\nYour temporary password is: {temp_pass}\n\nPlease login and change it immediately."
            mail.send(msg)
            # ADDED "success" category here
            flash("Check your email for the temporary password!", "success")
        except Exception as e:
            print(f"Mail failed: {e}")
            # ADDED "warning" category here (will show as red/yellow)
            flash("Teacher notified, but email failed to send.", "warning")

        db.session.commit()
    else:
        # ADDED "error" category here
        flash("No account found with that username or email.", "error")
        
    return redirect('/login')

@app.route('/teacher_dashboard')
def teacher_dashboard():
    if session.get('role') != 'teacher':
        return redirect('/login')
    
    # Fetch users who recently got a temporary password
    reset_users = User.query.filter_by(reset_requested=True).all()
    
    # Fetch all students for the "Manage Students" list
    all_students = User.query.filter_by(role='student').all()
    
    return render_template('teacher_dashboard.html', 
                           reset_users=reset_users, 
                           students=all_students)

@app.route('/teacher_reset/<int:user_id>')
def teacher_reset(user_id):
    if session.get('role') == 'teacher':
        user = User.query.get(user_id)
        if user:
            # Set to a default password they can change later
            user.password = generate_password_hash("default123", method='pbkdf2:sha256')
            user.reset_requested = False
            db.session.add(Notification(user_id=user.id, message="Your password was reset to: default123"))
            db.session.commit()
    return redirect('/')

@app.route('/clear_reset/<int:user_id>', methods=['POST'])
def clear_reset(user_id):
    if session.get('role') != 'teacher':
        return redirect('/login')
    
    user = User.query.get(user_id)
    if user:
        user.reset_requested = False  # This removes them from the red box
        db.session.commit()
    
    return redirect('/teacher_dashboard')

@app.route('/create_class', methods=['POST'])
def create_class():
    if session.get('role') == 'teacher':
        class_name = request.form.get('class_name')
        if class_name:
            db.session.add(Classroom(name=class_name))
            db.session.commit()
    return redirect('/')

@app.route('/view/<filename>')
def view_file(filename):
    # This looks in the materials folder
    return send_from_directory(os.path.join(app.config['UPLOAD_FOLDER'], 'materials'), filename)

@app.route('/view_assignment/<filename>')
def view_assignment(filename):
    # Flask example:
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename) 
    # Notice we don't use as_attachment=True here!    

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files: return redirect('/')
    file = request.files['file']
    if file.filename == '': return redirect('/')

    if session['role'] == 'teacher':
        classroom_id = request.form.get('classroom_id')
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], 'materials', file.filename))
        db.session.add(Material(title=file.filename, file_path=file.filename, class_id=classroom_id))
        
        classroom = Classroom.query.get(classroom_id)
        for s in classroom.students:
            db.session.add(Notification(user_id=s.id, message=f"New Material in {classroom.name}"))
    else:
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], 'assignments', file.filename))
        user = User.query.filter_by(username=session['username']).first()
        db.session.add(Submission(student_id=user.id, file_path=file.filename))
            
    db.session.commit()
    return redirect('/')

@app.route('/join_class', methods=['POST']) # No <int:class_id> here!
def join_class():
    student_id = session.get('user_id')
    if not student_id:
        return redirect(url_for('login'))

    # 1. Get the ID from the dropdown <select name="class_id">
    class_id = request.form.get('class_id')

    if not class_id:
        flash("Please select a class from the list!", "warning")
        return redirect(url_for('dashboard'))

    # 2. Check if a request already exists
    # We use .filter_by because enrollment_table is likely a model or Query object
    existing = db.session.query(enrollment_table).filter_by(
        user_id=student_id, 
        classroom_id=class_id
    ).first()
    
    if existing:
        flash("⏳ You already have a pending request for this class.", "info")
        return redirect(url_for('dashboard'))

    # 3. Insert the new request
    # Using your table name and standard SQLAlchemy insert
    try:
        new_req = enrollment_table.insert().values(
            user_id=student_id, 
            classroom_id=class_id, 
            status='pending'
        )
        db.session.execute(new_req)
        db.session.commit()
        flash("🚀 Success! Request sent to the teacher.", "success")
    except Exception as e:
        db.session.rollback()
        flash("❌ Error sending request. Please try again.", "danger")
        print(f"Enrollment Error: {e}")
    
    return redirect(url_for('dashboard'))

@app.route('/approve_student/<int:u_id>/<int:c_id>')
def approve_student(u_id, c_id):
    db.session.execute(enrollment_table.update().where(
        (enrollment_table.c.user_id == u_id) & (enrollment_table.c.classroom_id == c_id)
    ).values(status='approved'))
    db.session.add(Notification(user_id=u_id, message="Approved for class!"))
    db.session.commit()
    return redirect('/')

@app.route('/clear_notifications')
def clear_notifications():
    user = User.query.filter_by(username=session['username']).first()
    Notification.query.filter_by(user_id=user.id).update({'is_read': True})
    db.session.commit()
    return redirect('/')

# YOUR SPECIFIC DOWNLOAD/DELETE LOGIC (STRICTLY PRESERVED)
@app.route('/download_assignment/<filename>')
def download_assignment(filename):
    directory = os.path.join(app.config['UPLOAD_FOLDER'], 'assignments')
    should_download = request.args.get('download') == 'true'
    return send_from_directory(directory, filename, as_attachment=should_download)

@app.route('/delete_material/<int:id>')
def delete_material(id):
    item = Material.query.get(id)
    if item:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'materials', item.file_path)
        if os.path.exists(file_path): os.remove(file_path)
        db.session.delete(item)
        db.session.commit()
    return redirect('/')

@app.route('/grade/<int:submission_id>', methods=['POST'])
def give_grade(submission_id):
    new_score = request.form.get('grade_value')
    submission = Submission.query.get(submission_id)
    if submission:
        submission.grade = new_score
        db.session.add(Notification(user_id=submission.student_id, message=f"Grade: {new_score}"))
        db.session.commit()
    return redirect('/')

@app.route('/gallery')
def gallery():
    # This renders the new gallery.html file you created
    return render_template('gallery.html')

@app.route('/about')
def about():
    # This renders the new about.html file you created
    return render_template('about.html')

@app.route('/upload-snapshot', methods=['POST'])
def upload_snapshot():
    if session.get('role') != 'teacher':
        return "Unauthorized", 403

    if 'snapshot' not in request.files:
        return "No file part", 400
    
    file = request.files['snapshot']
    if file.filename == '':
        return "No selected file", 400

    if file:
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return redirect(url_for('gallery')) # Send them to the gallery to see it!

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

if __name__ == '__main__':
    # Separated by a COMMA, not a dot
    socketio.run(app, debug=True)