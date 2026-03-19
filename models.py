from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# 1. ENROLLMENT TABLE (Many-to-Many Join Table)
enrollment_table = db.Table('enrollment',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('classroom_id', db.Integer, db.ForeignKey('classroom.id'), primary_key=True),
    db.Column('status', db.String(20), default='pending'),
    extend_existing=True # This allows it to update if the table already exists
)

# 2. USER MODEL
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True) # Add this line
    password = db.Column(db.String(200), nullable=False)
    # ... rest of your model
    role = db.Column(db.String(20), nullable=False)
    reset_requested = db.Column(db.Boolean, default=False) # The new column
    
    classes = db.relationship('Classroom', secondary=enrollment_table, backref='students')

# 3. CLASSROOM MODEL
class Classroom(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    
    # Link to materials uploaded to this specific class
    materials = db.relationship('Material', backref='classroom', lazy=True)

# 4. MATERIAL MODEL
class Material(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    file_path = db.Column(db.String(200), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classroom.id'), nullable=True)

# 5. SUBMISSION MODEL (Combined and Fixed)
class Submission(db.Model):
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    file_path = db.Column(db.String(200), nullable=False)
    grade = db.Column(db.String(50), nullable=True)
    student_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # This relationship fixes the 'Submission object has no attribute student' error
    student = db.relationship('User', backref='student_submissions')

# 6. NOTIFICATION MODEL
class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.String(255), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=db.func.current_timestamp())
