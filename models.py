# models.py
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, date
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# --- User Model (NEW) ---
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    # CHANGE THIS LINE:
    password_hash = db.Column(db.String(255), nullable=False) # <--- Changed from 128 to 255

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.username}>"
        
class Cow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cow_id = db.Column(db.String(50), unique=True, nullable=False) # Unique ID/Name
    name = db.Column(db.String(100), nullable=False)
    breed = db.Column(db.String(100))
    date_of_birth = db.Column(db.Date)
    status = db.Column(db.String(50), default='active') # e.g., 'active', 'sold', 'deceased'

    milk_productions = db.relationship('MilkProduction', backref='cow', lazy=True)
    health_records = db.relationship('HealthRecord', backref='cow', lazy=True)

    def __repr__(self):
        return f"<Cow {self.name} ({self.cow_id})>"

class MilkProduction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cow_id = db.Column(db.Integer, db.ForeignKey('cow.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, default=date.today)
    morning_qty_liters = db.Column(db.Float, nullable=False)
    evening_qty_liters = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow) # When the log was created

    def total_daily_quantity(self):
        return self.morning_qty_liters + self.evening_qty_liters

    def __repr__(self):
        return f"<MilkProd {self.cow.name} on {self.date}: {self.total_daily_quantity()}L>"

class HealthRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cow_id = db.Column(db.Integer, db.ForeignKey('cow.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, default=date.today)
    description = db.Column(db.Text, nullable=False)
    treatment = db.Column(db.Text)
    veterinarian = db.Column(db.String(100))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<HealthRecord {self.cow.name} on {self.date}: {self.description[:30]}...>"

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    contact_info = db.Column(db.Text)
    balance = db.Column(db.Float, default=0.0) # Amount owed by customer

    sales = db.relationship('Sale', backref='customer', lazy=True)
    payments = db.relationship('Payment', backref='customer', lazy=True)

    def __repr__(self):
        return f"<Customer {self.name} (Balance: {self.balance:.2f})>"

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, default=date.today)
    milk_quantity_liters = db.Column(db.Float, nullable=False)
    price_per_liter = db.Column(db.Float, nullable=False)
    total_amount = db.Column(db.Float, nullable=False) # Calculated
    is_paid = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Sale {self.customer.name} on {self.date}: {self.total_amount:.2f}>"

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, default=date.today)
    amount_received = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Payment {self.customer.name} on {self.date}: {self.amount_received:.2f}>"

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, default=date.today)
    category = db.Column(db.String(100), nullable=False) # e.g., 'Feed', 'Veterinary', 'Labor'
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Expense {self.category} on {self.date}: {self.amount:.2f}>"
