from app import db
from datetime import datetime
from sqlalchemy.dialects.sqlite import JSON

# Association table for rejected matches (Memory)
rejected_matches = db.Table('rejected_matches',
    db.Column('face_id', db.Integer, db.ForeignKey('faces.id'), primary_key=True),
    db.Column('person_id', db.Integer, db.ForeignKey('people.id'), primary_key=True),
    db.Column('rejected_at', db.DateTime, default=datetime.utcnow)
)

class Asset(db.Model):
    __tablename__ = 'assets'
    id = db.Column(db.Integer, primary_key=True)
    file_path = db.Column(db.String, nullable=False, unique=True, index=True)
    file_hash = db.Column(db.String, index=True)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    captured_at = db.Column(db.DateTime, index=True)
    media_type = db.Column(db.String)
    title = db.Column(db.String)
    meta_json = db.Column(JSON)

    faces = db.relationship('Face', backref='asset', lazy='dynamic')

class Person(db.Model):
    __tablename__ = 'people'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False, unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    faces = db.relationship('Face', backref='person', lazy='dynamic')
    rejected_faces = db.relationship('Face', secondary='rejected_matches', 
                                   backref=db.backref('rejected_by_people', lazy='dynamic'), 
                                   lazy='dynamic')

class Face(db.Model):
    __tablename__ = 'faces'
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('assets.id'))
    person_id = db.Column(db.Integer, db.ForeignKey('people.id'), nullable=True)
    encoding = db.Column(db.LargeBinary) # Storing blob for numpy array
    location = db.Column(JSON) # [top, right, bottom, left]
    confidence = db.Column(db.Float)
    is_confirmed = db.Column(db.Boolean, default=False)

class LibraryPath(db.Model):
    __tablename__ = 'library_paths'
    id = db.Column(db.Integer, primary_key=True)
    path = db.Column(db.String, nullable=False, unique=True)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_scanned = db.Column(db.DateTime, nullable=True)
