import os
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
# Only import the models you need to directly query in this file
from models import Cow, MilkProduction, HealthRecord, Customer, Sale, Payment, Expense, User, Vaccination
from datetime import date, datetime, timedelta
from sqlalchemy import func, extract
from config import Config
import click
import pandas as pd
import io
# NEW: Import db and login_manager from extensions
from extensions import db, login_manager # <--- NEW IMPORT

app = Flask(__name__)
app.config.from_object(Config)

# Initialize extensions with the app instance
db.init_app(app)
login_manager.init_app(app) # Initialize login_manager here
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# --- Context Processor ---
@app.context_processor
def inject_common_variables():
    return {
        'today': date.today(),
        'now': datetime.now,
        'current_user': current_user
    }

# --- Flask CLI Custom Commands ---
@app.cli.command("create-db")
def create_db_command():
    """Creates the database tables."""
    with app.app_context(): # Ensure we are in the app context
        instance_path = os.path.join(app.root_path, 'instance')
        if not os.path.exists(instance_path):
            os.makedirs(instance_path)
            click.echo(f"Created instance directory: {instance_path}")
        
        # Ensure all models are loaded before calling create_all
        # (They usually are due to imports at top, but explicit import can help in complex setups)
        # from models import User, Cow, MilkProduction, HealthRecord, Customer, Sale, Payment, Expense, Vaccination 

        db.create_all()
        click.echo("Database tables created!")

@app.cli.command("create-admin-user")
@click.argument('username')
@click.argument('password')
def create_admin_user_command(username, password):
    """Creates an initial admin user."""
    with app.app_context(): # Ensure we are in the app context
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            click.echo(f"User '{username}' already exists. Please choose a different username.")
            return

        new_user = User(username=username)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        click.echo(f"Admin user '{username}' created successfully!")


# --- Authentication Routes ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()

        if user is None or not user.check_password(password):
            flash('Invalid username or password', 'danger')
            return render_template('login.html', username=username)
        
        login_user(user)
        flash('Logged in successfully!', 'success')
        next_page = request.args.get('next')
        return redirect(next_page or url_for('index'))

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# --- Protected Routes ---
@app.route('/')
@login_required
def index():
    total_cows = Cow.query.count()
    active_cows = Cow.query.filter_by(status='active').count()

    today_date = date.today()
    today_milk_records = MilkProduction.query.filter_by(date=today_date).all()
    total_today_milk = sum(rec.total_daily_quantity() for rec in today_milk_records)

    total_receivable = db.session.query(func.sum(Customer.balance)).scalar() or 0.0

    recent_sales = Sale.query.order_by(Sale.timestamp.desc()).limit(5).all()
    recent_expenses = Expense.query.order_by(Expense.timestamp.desc()).limit(5).all()

    # --- NEW: Reminder Logic for Dashboard ---
    upcoming_vaccinations = []
    # Vaccinations due within the next 30 days
    vaccination_reminder_window = today_date + timedelta(days=30)
    upcoming_vaccinations = Vaccination.query.filter(
        Vaccination.next_due_date >= today_date,
        Vaccination.next_due_date <= vaccination_reminder_window
    ).order_by(Vaccination.next_due_date).all()

    pregnant_cow_reminders = []
    # Pregnant cows with due date within the next 4 days
    pregnancy_start_window = today_date
    pregnancy_end_window = today_date + timedelta(days=4)
    pregnant_cow_reminders = Cow.query.filter(
        Cow.is_pregnant == True,
        Cow.pregnancy_due_date >= pregnancy_start_window,
        Cow.pregnancy_due_date <= pregnancy_end_window
    ).order_by(Cow.pregnancy_due_date).all()


    return render_template('index.html',
                           total_cows=total_cows,
                           active_cows=active_cows,
                           total_today_milk=total_today_milk,
                           total_receivable=total_receivable,
                           recent_sales=recent_sales,
                           recent_expenses=recent_expenses,
                           upcoming_vaccinations=upcoming_vaccinations, # <--- Pass to template
                           pregnant_cow_reminders=pregnant_cow_reminders) # <--- Pass to template

# --- Cow Management (UPDATE: add pregnancy fields) ---
@app.route('/cows')
@login_required
def view_cows():
    cows = Cow.query.all()
    return render_template('view_cows.html', cows=cows)

@app.route('/cows/add', methods=['GET', 'POST'])
@login_required
def add_cow():
    if request.method == 'POST':
        cow_id = request.form['cow_id']
        name = request.form['name']
        breed = request.form.get('breed')
        date_of_birth_str = request.form.get('date_of_birth')
        is_pregnant = 'is_pregnant' in request.form # Checkbox value
        pregnancy_due_date_str = request.form.get('pregnancy_due_date')

        date_of_birth = None
        if date_of_birth_str:
            try:
                date_of_birth = datetime.strptime(date_of_birth_str, '%Y-%m-%d').date()
            except ValueError:
                flash("Invalid date format for Date of Birth. Please use YYYY-MM-DD.", 'danger')
                return render_template('add_cow.html', **request.form) # Pass form data back

        pregnancy_due_date = None
        if is_pregnant and pregnancy_due_date_str:
            try:
                pregnancy_due_date = datetime.strptime(pregnancy_due_date_str, '%Y-%m-%d').date()
            except ValueError:
                flash("Invalid date format for Pregnancy Due Date. Please use YYYY-MM-DD.", 'danger')
                return render_template('add_cow.html', **request.form)

        existing_cow = Cow.query.filter_by(cow_id=cow_id).first()
        if existing_cow:
            flash(f"Cow ID '{cow_id}' already exists. Please use a unique ID.", 'danger')
            return render_template('add_cow.html', **request.form)


        new_cow = Cow(cow_id=cow_id, name=name, breed=breed, date_of_birth=date_of_birth,
                      is_pregnant=is_pregnant, pregnancy_due_date=pregnancy_due_date)
        try:
            db.session.add(new_cow)
            db.session.commit()
            flash(f'Cow "{name}" ({cow_id}) added successfully!', 'success')
            return redirect(url_for('view_cows'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding cow: {str(e)}', 'danger')
    return render_template('add_cow.html')

@app.route('/cows/edit/<int:cow_id>', methods=['GET', 'POST'])
@login_required
def edit_cow(cow_id):
    cow = db.session.get(Cow, cow_id)
    if cow is None:
        flash('Cow not found.', 'danger')
        abort(404)

    if request.method == 'POST':
        cow.cow_id = request.form['cow_id']
        cow.name = request.form['name']
        cow.breed = request.form.get('breed')
        date_of_birth_str = request.form.get('date_of_birth')
        expected_calving_date_str = request.form.get('expected_calving_date')
        cow.is_pregnant = bool(request.form.get('is_pregnant')) 
        cow.status = request.form['status']

        date_of_birth = None
        if date_of_birth_str:
            try:
                date_of_birth = datetime.strptime(date_of_birth_str, '%Y-%m-%d').date()
            except ValueError:
                flash("Invalid date format for Date of Birth. Please use YYYY-MM-DD.", 'danger')
                return render_template('edit_cow.html', cow=cow, **request.form)
        cow.date_of_birth = date_of_birth

        expected_calving_date = None
        if expected_calving_date_str:
            try:
                expected_calving_date = datetime.strptime(expected_calving_date_str, '%Y-%m-%d').date()
            except ValueError:
                flash("Invalid date format for Expected Calving Date. Please use YYYY-MM-DD.", 'danger')
                return render_template('edit_cow.html', cow=cow, **request.form)
        cow.expected_calving_date = expected_calving_date

        try:
            db.session.commit()
            flash(f'Cow "{cow.name}" ({cow.cow_id}) updated successfully!', 'success')
            return redirect(url_for('view_cows'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating cow: {str(e)}', 'danger')

    return render_template('edit_cow.html', cow=cow)

@app.route('/cows/delete/<int:cow_id>', methods=['POST'])
@login_required
def delete_cow(cow_id):
    cow = db.session.get(Cow, cow_id)
    if cow is None:
        flash('Cow not found.', 'danger')
        abort(404)

    try:
        # Delete related records due to foreign key constraints
        MilkProduction.query.filter_by(cow_id=cow.id).delete()
        HealthRecord.query.filter_by(cow_id=cow.id).delete()
        Vaccination.query.filter_by(cow_id=cow.id).delete()

        db.session.delete(cow)
        db.session.commit()
        flash(f'Cow "{cow.name}" ({cow.cow_id}) and all related records deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting cow: {str(e)}', 'danger')
    return redirect(url_for('view_cows'))


# --- Milk Production Routes (Existing) ---
@app.route('/milk_production/log', methods=['GET', 'POST'])
@login_required
def log_milk_production():
    cows = Cow.query.filter_by(status='active').all()
    if request.method == 'POST':
        cow_id = request.form['cow_id']
        date_str = request.form['date']
        morning_qty = float(request.form['morning_qty'])
        evening_qty = float(request.form['evening_qty'])

        cow = Cow.query.get(cow_id)
        if not cow:
            flash('Cow not found!', 'danger')
            return render_template('log_milk_production.html', cows=cows, **request.form)

        try:
            log_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD.", 'danger')
            return render_template('log_milk_production.html', cows=cows, **request.form)

        new_log = MilkProduction(
            cow_id=cow.id,
            date=log_date,
            morning_qty_liters=morning_qty,
            evening_qty_liters=evening_qty
        )
        try:
            db.session.add(new_log)
            db.session.commit()
            flash(f'Milk production for {cow.name} on {log_date} logged successfully!', 'success')
            return redirect(url_for('milk_history'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error logging milk production: {str(e)}', 'danger')
    return render_template('log_milk_production.html', cows=cows)

@app.route('/milk_production/history')
@login_required
def milk_history():
    milk_records = MilkProduction.query.order_by(MilkProduction.date.desc(), MilkProduction.timestamp.desc()).all()
    return render_template('milk_history.html', milk_records=milk_records)

@app.route('/milk_production/edit/<int:record_id>', methods=['GET', 'POST']) # <--- NEW EDIT MILK PRODUCTION
@login_required
def edit_milk_production(record_id):
    record = db.session.get(MilkProduction, record_id)
    if record is None:
        flash('Milk production record not found.', 'danger')
        abort(404)
    cows = Cow.query.filter_by(status='active').all()

    if request.method == 'POST':
        record.cow_id = request.form['cow_id']
        date_str = request.form['date']
        record.morning_qty_liters = float(request.form['morning_qty'])
        record.evening_qty_liters = float(request.form['evening_qty'])

        try:
            record.date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD.", 'danger')
            return render_template('edit_milk_production.html', record=record, cows=cows, **request.form)
        
        try:
            db.session.commit()
            flash(f'Milk production for {record.cow.name} on {record.date} updated successfully!', 'success')
            return redirect(url_for('milk_history'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating milk production: {str(e)}', 'danger')
    
    return render_template('edit_milk_production.html', record=record, cows=cows)

@app.route('/milk_production/delete/<int:record_id>', methods=['POST']) # <--- NEW DELETE MILK PRODUCTION
@login_required
def delete_milk_production(record_id):
    record = db.session.get(MilkProduction, record_id)
    if record is None:
        flash('Milk production record not found.', 'danger')
        abort(404)
    
    try:
        db.session.delete(record)
        db.session.commit()
        flash(f'Milk production record for {record.cow.name} on {record.date} deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting milk production: {str(e)}', 'danger')
    return redirect(url_for('milk_history'))


# --- Health Record Routes ---
@app.route('/health_records/add', methods=['GET', 'POST'])
@login_required
def add_health_record():
    cows = Cow.query.filter_by(status='active').all()
    if request.method == 'POST':
        cow_id = request.form['cow_id']
        date_str = request.form['date']
        description = request.form['description']
        treatment = request.form.get('treatment')
        veterinarian = request.form.get('veterinarian')

        cow = Cow.query.get(cow_id)
        if not cow:
            flash('Cow not found!', 'danger')
            return render_template('add_health_record.html', cows=cows, **request.form)

        try:
            record_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD.", 'danger')
            return render_template('add_health_record.html', cows=cows, **request.form)

        new_record = HealthRecord(
            cow_id=cow.id,
            date=record_date,
            description=description,
            treatment=treatment,
            veterinarian=veterinarian
        )
        try:
            db.session.add(new_record)
            db.session.commit()
            flash(f'Health record for {cow.name} on {record_date} added successfully!', 'success')
            return redirect(url_for('view_health_records'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding health record: {str(e)}', 'danger')
    return render_template('add_health_record.html', cows=cows)

@app.route('/health_records')
@login_required
def view_health_records():
    health_records = HealthRecord.query.order_by(HealthRecord.date.desc(), HealthRecord.timestamp.desc()).all()
    return render_template('view_health_records.html', health_records=health_records)

@app.route('/health_records/edit/<int:record_id>', methods=['GET', 'POST']) # <--- NEW EDIT HEALTH RECORD
@login_required
def edit_health_record(record_id):
    record = db.session.get(HealthRecord, record_id)
    if record is None:
        flash('Health record not found.', 'danger')
        abort(404)
    cows = Cow.query.filter_by(status='active').all()

    if request.method == 'POST':
        record.cow_id = request.form['cow_id']
        date_str = request.form['date']
        record.description = request.form['description']
        record.treatment = request.form.get('treatment')
        record.veterinarian = request.form.get('veterinarian')

        try:
            record.date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD.", 'danger')
            return render_template('edit_health_record.html', record=record, cows=cows, **request.form)
        
        try:
            db.session.commit()
            flash(f'Health record for {record.cow.name} on {record.date} updated successfully!', 'success')
            return redirect(url_for('view_health_records'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating health record: {str(e)}', 'danger')
    
    return render_template('edit_health_record.html', record=record, cows=cows)

@app.route('/health_records/delete/<int:record_id>', methods=['POST']) # <--- NEW DELETE HEALTH RECORD
@login_required
def delete_health_record(record_id):
    record = db.session.get(HealthRecord, record_id)
    if record is None:
        flash('Health record not found.', 'danger')
        abort(404)
    
    try:
        db.session.delete(record)
        db.session.commit()
        flash(f'Health record for {record.cow.name} on {record.date} deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting health record: {str(e)}', 'danger')
    return redirect(url_for('view_health_records'))


# --- NEW: Vaccination Routes ---
@app.route('/vaccinations/add', methods=['GET', 'POST'])
@login_required
def add_vaccination():
    cows = Cow.query.filter_by(status='active').all()
    if request.method == 'POST':
        cow_id = request.form['cow_id']
        vaccine_name = request.form['vaccine_name']
        vaccination_date_str = request.form['vaccination_date']
        next_due_date_str = request.form.get('next_due_date')
        notes = request.form.get('notes')

        cow = Cow.query.get(cow_id)
        if not cow:
            flash('Cow not found!', 'danger')
            return render_template('add_vaccination.html', cows=cows, **request.form)

        try:
            vaccination_date = datetime.strptime(vaccination_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash("Invalid date format for Vaccination Date. Please use YYYY-MM-DD.", 'danger')
            return render_template('add_vaccination.html', cows=cows, **request.form)

        next_due_date = None
        if next_due_date_str:
            try:
                next_due_date = datetime.strptime(next_due_date_str, '%Y-%m-%d').date()
            except ValueError:
                flash("Invalid date format for Next Due Date. Please use YYYY-MM-DD.", 'danger')
                return render_template('add_vaccination.html', cows=cows, **request.form)

        new_vaccination = Vaccination(
            cow_id=cow.id,
            vaccine_name=vaccine_name,
            vaccination_date=vaccination_date,
            next_due_date=next_due_date,
            notes=notes
        )
        try:
            db.session.add(new_vaccination)
            db.session.commit()
            flash(f'Vaccination record for {cow.name} ({vaccine_name}) added successfully!', 'success')
            return redirect(url_for('view_vaccinations'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding vaccination: {str(e)}', 'danger')
    return render_template('add_vaccination.html', cows=cows)

@app.route('/vaccinations')
@login_required
def view_vaccinations():
    vaccinations = Vaccination.query.order_by(Vaccination.vaccination_date.desc()).all()
    return render_template('view_vaccinations.html', vaccinations=vaccinations)

@app.route('/vaccinations/delete/<int:id>', methods=['POST'])
@login_required
def delete_vaccination(id):
    vaccination_record = db.session.get(Vaccination, id)
    if not vaccination_record:
        flash('Vaccination record not found.', 'danger')
        return redirect(url_for('view_vaccinations'))

    try:
        # FIX FOR DELETION ERROR: Get related data BEFORE deleting and committing
        cow_name = vaccination_record.cow.name if vaccination_record.cow else 'Unknown Cow'
        vaccine_name = vaccination_record.vaccine_name

        db.session.delete(vaccination_record)
        db.session.commit()
        flash(f'Vaccination record for {cow_name} ({vaccine_name}) deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting vaccination: {str(e)}', 'danger')
    return redirect(url_for('view_vaccinations'))


# --- Customer Management ---
@app.route('/customers')
@login_required
def view_customers():
    customers = Customer.query.order_by(Customer.name).all()
    return render_template('view_customers.html', customers=customers)

@app.route('/customers/add', methods=['GET', 'POST'])
@login_required
def add_customer():
    if request.method == 'POST':
        name = request.form['name']
        contact_info = request.form.get('contact_info')

        new_customer = Customer(name=name, contact_info=contact_info)
        try:
            db.session.add(new_customer)
            db.session.commit()
            flash(f'Customer "{name}" added successfully!', 'success')
            return redirect(url_for('view_customers'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding customer: {str(e)}', 'danger')
    return render_template('add_customer.html')

@app.route('/customers/edit/<int:customer_id>', methods=['GET', 'POST']) # <--- NEW EDIT CUSTOMER
@login_required
def edit_customer(customer_id):
    customer = db.session.get(Customer, customer_id)
    if customer is None:
        flash('Customer not found.', 'danger')
        abort(404)
    
    if request.method == 'POST':
        customer.name = request.form['name']
        customer.contact_info = request.form.get('contact_info')
        # Note: balance is updated via sales/payments, not directly edited here

        try:
            db.session.commit()
            flash(f'Customer "{customer.name}" updated successfully!', 'success')
            return redirect(url_for('view_customers'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating customer: {str(e)}', 'danger')
            
    return render_template('edit_customer.html', customer=customer)

@app.route('/customers/delete/<int:customer_id>', methods=['POST']) # <--- NEW DELETE CUSTOMER
@login_required
def delete_customer(customer_id):
    customer = db.session.get(Customer, customer_id)
    if customer is None:
        flash('Customer not found.', 'danger')
        abort(404)

    try:
        # Delete related sales and payments first due to foreign key constraints
        Sale.query.filter_by(customer_id=customer.id).delete()
        Payment.query.filter_by(customer_id=customer.id).delete()

        db.session.delete(customer)
        db.session.commit()
        flash(f'Customer "{customer.name}" and all related transactions deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting customer: {str(e)}', 'danger')
    return redirect(url_for('view_customers'))


# --- Sales Routes ---
@app.route('/sales/record', methods=['GET', 'POST'])
@login_required
def record_sale():
    customers = Customer.query.order_by(Customer.name).all()
    if request.method == 'POST':
        customer_id = request.form['customer_id']
        date_str = request.form['date']
        milk_qty = float(request.form['milk_qty'])
        price_per_liter = float(request.form['price_per_liter'])

        customer = Customer.query.get(customer_id)
        if not customer:
            flash('Customer not found!', 'danger')
            return render_template('record_sale.html', customers=customers, **request.form)

        try:
            sale_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD.", 'danger')
            return render_template('record_sale.html', customers=customers, **request.form)

        total_amount = milk_qty * price_per_liter
        new_sale = Sale(
            customer_id=customer.id,
            date=sale_date,
            milk_quantity_liters=milk_qty,
            price_per_liter=price_per_liter,
            total_amount=total_amount
        )
        try:
            db.session.add(new_sale)
            customer.balance += total_amount # Update customer's balance
            db.session.commit()
            flash(f'Sale to {customer.name} recorded successfully! Amount: {total_amount:.2f}', 'success')
            return redirect(url_for('view_sales'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error recording sale: {str(e)}', 'danger')
    return render_template('record_sale.html', customers=customers)

@app.route('/sales')
@login_required
def view_sales():
    sales = Sale.query.order_by(Sale.date.desc(), Sale.timestamp.desc()).all()
    return render_template('view_sales.html', sales=sales)

@app.route('/sales/edit/<int:sale_id>', methods=['GET', 'POST']) # <--- NEW EDIT SALE
@login_required
def edit_sale(sale_id):
    sale = db.session.get(Sale, sale_id)
    if sale is None:
        flash('Sale record not found.', 'danger')
        abort(404)
    customers = Customer.query.order_by(Customer.name).all()

    if request.method == 'POST':
        old_total_amount = sale.total_amount # Store old amount for balance adjustment
        
        sale.customer_id = request.form['customer_id']
        date_str = request.form['date']
        milk_qty = float(request.form['milk_qty'])
        price_per_liter = float(request.form['price_per_liter'])
        sale.is_paid = bool(request.form.get('is_paid')) # Checkbox

        try:
            sale.date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD.", 'danger')
            return render_template('edit_sale.html', sale=sale, customers=customers, **request.form)

        sale.milk_quantity_liters = milk_qty
        sale.price_per_liter = price_per_liter
        sale.total_amount = milk_qty * price_per_liter # Recalculate total amount

        try:
            # Adjust customer balance based on the change in total_amount
            customer = db.session.get(Customer, sale.customer_id)
            customer.balance -= old_total_amount # Subtract old amount
            customer.balance += sale.total_amount # Add new amount
            
            db.session.commit()
            flash(f'Sale record updated successfully! New Amount: {sale.total_amount:.2f}', 'success')
            return redirect(url_for('view_sales'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating sale: {str(e)}', 'danger')
            
    return render_template('edit_sale.html', sale=sale, customers=customers)

@app.route('/sales/delete/<int:sale_id>', methods=['POST']) # <--- NEW DELETE SALE
@login_required
def delete_sale(sale_id):
    sale = db.session.get(Sale, sale_id)
    if sale is None:
        flash('Sale record not found.', 'danger')
        abort(404)
    
    try:
        # Adjust customer balance before deleting the sale
        customer = db.session.get(Customer, sale.customer_id)
        customer.balance -= sale.total_amount # Subtract the amount of the deleted sale

        db.session.delete(sale)
        db.session.commit()
        flash(f'Sale record of {sale.total_amount:.2f} deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting sale: {str(e)}', 'danger')
    return redirect(url_for('view_sales'))


# --- Payments Routes ---
@app.route('/payments/record', methods=['GET', 'POST'])
@login_required
def record_payment():
    customers = Customer.query.order_by(Customer.name).all()
    if request.method == 'POST':
        customer_id = request.form['customer_id']
        date_str = request.form['date']
        amount_received = float(request.form['amount_received'])
        description = request.form.get('description')

        customer = Customer.query.get(customer_id)
        if not customer:
            flash('Customer not found!', 'danger')
            return render_template('record_payment.html', customers=customers, **request.form)

        try:
            payment_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD.", 'danger')
            return render_template('record_payment.html', customers=customers, **request.form)

        new_payment = Payment(
            customer_id=customer.id,
            date=payment_date,
            amount_received=amount_received,
            description=description
        )
        try:
            db.session.add(new_payment)
            customer.balance -= amount_received # Update customer's balance (payment reduces what they owe)
            db.session.commit()
            flash(f'Payment from {customer.name} recorded successfully! Amount: {amount_received:.2f}', 'success')
            return redirect(url_for('view_payments'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error recording payment: {str(e)}', 'danger')
    return render_template('record_payment.html', customers=customers)

@app.route('/payments')
@login_required
def view_payments():
    payments = Payment.query.order_by(Payment.date.desc(), Payment.timestamp.desc()).all()
    return render_template('view_payments.html', payments=payments)

@app.route('/payments/edit/<int:payment_id>', methods=['GET', 'POST']) # <--- NEW EDIT PAYMENT
@login_required
def edit_payment(payment_id):
    payment = db.session.get(Payment, payment_id)
    if payment is None:
        flash('Payment record not found.', 'danger')
        abort(404)
    customers = Customer.query.order_by(Customer.name).all()

    if request.method == 'POST':
        old_amount_received = payment.amount_received # Store old amount for balance adjustment
        
        payment.customer_id = request.form['customer_id']
        date_str = request.form['date']
        amount_received = float(request.form['amount_received'])
        payment.description = request.form.get('description')

        try:
            payment.date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD.", 'danger')
            return render_template('edit_payment.html', payment=payment, customers=customers, **request.form)

        payment.amount_received = amount_received

        try:
            # Adjust customer balance based on the change in amount_received
            customer = db.session.get(Customer, payment.customer_id)
            customer.balance += old_amount_received # Add old amount back
            customer.balance -= payment.amount_received # Subtract new amount
            
            db.session.commit()
            flash(f'Payment record updated successfully! New Amount: {payment.amount_received:.2f}', 'success')
            return redirect(url_for('view_payments'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating payment: {str(e)}', 'danger')
            
    return render_template('edit_payment.html', payment=payment, customers=customers)

@app.route('/payments/delete/<int:payment_id>', methods=['POST']) # <--- NEW DELETE PAYMENT
@login_required
def delete_payment(payment_id):
    payment = db.session.get(Payment, payment_id)
    if payment is None:
        flash('Payment record not found.', 'danger')
        abort(404)
    
    try:
        # Adjust customer balance before deleting the payment
        customer = db.session.get(Customer, payment.customer_id)
        customer.balance += payment.amount_received # Add amount back to what they owe

        db.session.delete(payment)
        db.session.commit()
        flash(f'Payment record of {payment.amount_received:.2f} deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting payment: {str(e)}', 'danger')
    return redirect(url_for('view_payments'))


# --- Expenses Routes ---
@app.route('/expenses/record', methods=['GET', 'POST'])
@login_required
def record_expense():
    if request.method == 'POST':
        date_str = request.form['date']
        category = request.form['category']
        amount = float(request.form['amount'])
        description = request.form.get('description')

        try:
            expense_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD.", 'danger')
            return render_template('record_expense.html', **request.form)

        new_expense = Expense(
            date=expense_date,
            category=category,
            amount=amount,
            description=description
        )
        try:
            db.session.add(new_expense)
            db.session.commit()
            flash(f'Expense "{category}" of {amount:.2f} recorded successfully!', 'success')
            return redirect(url_for('view_expenses'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error recording expense: {str(e)}', 'danger')
    return render_template('record_expense.html')

@app.route('/expenses')
@login_required
def view_expenses():
    expenses = Expense.query.order_by(Expense.date.desc(), Expense.timestamp.desc()).all()
    return render_template('view_expenses.html', expenses=expenses)

@app.route('/expenses/edit/<int:expense_id>', methods=['GET', 'POST']) # <--- NEW EDIT EXPENSE
@login_required
def edit_expense(expense_id):
    expense = db.session.get(Expense, expense_id)
    if expense is None:
        flash('Expense record not found.', 'danger')
        abort(404)
    
    if request.method == 'POST':
        date_str = request.form['date']
        expense.category = request.form['category']
        expense.amount = float(request.form['amount'])
        expense.description = request.form.get('description')

        try:
            expense.date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD.", 'danger')
            return render_template('edit_expense.html', expense=expense, **request.form)
        
        try:
            db.session.commit()
            flash(f'Expense "{expense.category}" of {expense.amount:.2f} updated successfully!', 'success')
            return redirect(url_for('view_expenses'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating expense: {str(e)}', 'danger')
            
    return render_template('edit_expense.html', expense=expense)

@app.route('/expenses/delete/<int:expense_id>', methods=['POST']) # <--- NEW DELETE EXPENSE
@login_required
def delete_expense(expense_id):
    expense = db.session.get(Expense, expense_id)
    if expense is None:
        flash('Expense record not found.', 'danger')
        abort(404)
    
    try:
        db.session.delete(expense)
        db.session.commit()
        flash(f'Expense "{expense.category}" of {expense.amount:.2f} deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting expense: {str(e)}', 'danger')
    return redirect(url_for('view_expenses'))


# --- Reports Routes (Existing) ---
@app.route('/profit_loss', methods=['GET', 'POST'])
@login_required
def profit_loss(): # ... (code unchanged) ...
    start_date = None
    end_date = None
    total_income = 0.0
    total_expenses = 0.0
    net_profit_loss = 0.0
    transactions = []

    if request.method == 'POST':
        start_date_str = request.form.get('start_date')
        end_date_str = request.form.get('end_date')

        try:
            if start_date_str:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            if end_date_str:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD.", 'danger')
            return render_template('profit_loss.html')

        sales_query = db.session.query(func.sum(Sale.total_amount))
        if start_date:
            sales_query = sales_query.filter(Sale.date >= start_date)
        if end_date:
            sales_query = sales_query.filter(Sale.date <= end_date)
        total_income = sales_query.scalar() or 0.0

        expenses_query = db.session.query(func.sum(Expense.amount))
        if start_date:
            expenses_query = expenses_query.filter(Expense.date >= start_date)
        if end_date:
            expenses_query = expenses_query.filter(Expense.date <= end_date)
        total_expenses = expenses_query.scalar() or 0.0

        net_profit_loss = total_income - total_expenses

        sales_data = Sale.query
        expenses_data = Expense.query

        if start_date:
            sales_data = sales_data.filter(Sale.date >= start_date)
            expenses_data = expenses_data.filter(Expense.date >= start_date)
        if end_date:
            sales_data = sales_data.filter(Sale.date <= end_date)
            expenses_data = expenses_data.filter(Expense.date <= end_date)

        transactions.extend(sales_data.order_by(Sale.date.desc()).all())
        transactions.extend(expenses_data.order_by(Expense.date.desc()).all())
        transactions.sort(key=lambda x: x.date, reverse=True)

    return render_template('profit_loss.html',
                           start_date=start_date,
                           end_date=end_date,
                           total_income=total_income,
                           total_expenses=total_expenses,
                           net_profit_loss=net_profit_loss,
                           transactions=transactions)


@app.route('/amounts_receivable')
@login_required
def amounts_receivable():
    customers_owing = Customer.query.filter(Customer.balance > 0).order_by(Customer.name).all()
    return render_template('amounts_receivable.html', customers_owing=customers_owing)

# --- EXPORT ROUTES (Existing) ---
@app.route('/export/milk_production')
@login_required
def export_milk_production(): # ... (code unchanged) ...
    milk_records = MilkProduction.query.all()
    data = []
    for record in milk_records:
        data.append({
            'Date': record.date.strftime('%Y-%m-%d'),
            'Cow Name': record.cow.name,
            'Cow ID': record.cow.cow_id,
            'Morning Quantity (L)': record.morning_qty_liters,
            'Evening Quantity (L)': record.evening_qty_liters,
            'Total Daily Quantity (L)': record.total_daily_quantity(),
            'Logged At': record.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        })

    df = pd.DataFrame(data)
    output = io.BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')
    df.to_excel(writer, index=False, sheet_name='Milk Production')
    writer.close()
    output.seek(0)

    return send_file(output, as_attachment=True, download_name=f'milk_production_{date.today().strftime("%Y%m%d")}.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.route('/export/health_records')
@login_required
def export_health_records(): # ... (code unchanged) ...
    health_records = HealthRecord.query.all()
    data = []
    for record in health_records:
        data.append({
            'Date': record.date.strftime('%Y-%m-%d'),
            'Cow Name': record.cow.name,
            'Cow ID': record.cow.cow_id,
            'Description': record.description,
            'Treatment': record.treatment,
            'Veterinarian': record.veterinarian,
            'Logged At': record.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        })

    df = pd.DataFrame(data)
    output = io.BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')
    df.to_excel(writer, index=False, sheet_name='Health Records')
    writer.close()
    output.seek(0)

    return send_file(output, as_attachment=True, download_name=f'health_records_{date.today().strftime("%Y%m%d")}.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/export/sales')
@login_required
def export_sales(): # ... (code unchanged) ...
    sales = Sale.query.all()
    data = []
    for record in sales:
        data.append({
            'Date': record.date.strftime('%Y-%m-%d'),
            'Customer Name': record.customer.name,
            'Milk Quantity (L)': record.milk_quantity_liters,
            'Price Per Liter (RWF)': record.price_per_liter,
            'Total Amount (RWF)': record.total_amount,
            'Is Paid': 'Yes' if record.is_paid else 'No',
            'Logged At': record.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        })

    df = pd.DataFrame(data)
    output = io.BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')
    df.to_excel(writer, index=False, sheet_name='Sales')
    writer.close()
    output.seek(0)

    return send_file(output, as_attachment=True, download_name=f'sales_history_{date.today().strftime("%Y%m%d")}.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/export/payments')
@login_required
def export_payments(): # ... (code unchanged) ...
    payments = Payment.query.all()
    data = []
    for record in payments:
        data.append({
            'Date': record.date.strftime('%Y-%m-%d'),
            'Customer Name': record.customer.name,
            'Amount Received (RWF)': record.amount_received,
            'Description': record.description,
            'Logged At': record.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        })

    df = pd.DataFrame(data)
    output = io.BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')
    df.to_excel(writer, index=False, sheet_name='Payments')
    writer.close()
    output.seek(0)

    return send_file(output, as_attachment=True, download_name=f'payments_history_{date.today().strftime("%Y%m%d")}.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/export/expenses')
@login_required
def export_expenses(): # ... (code unchanged) ...
    expenses = Expense.query.all()
    data = []
    for record in expenses:
        data.append({
            'Date': record.date.strftime('%Y-%m-%m'),
            'Category': record.category,
            'Amount (RWF)': record.amount,
            'Description': record.description,
            'Logged At': record.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        })

    df = pd.DataFrame(data)
    output = io.BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')
    df.to_excel(writer, index=False, sheet_name='Expenses')
    writer.close()
    output.seek(0)

    return send_file(output, as_attachment=True, download_name=f'expenses_history_{date.today().strftime("%Y%m%d")}.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/export/vaccinations')
@login_required
def export_vaccinations():
    vaccinations = Vaccination.query.all()
    data = []
    for vac in vaccinations:
        data.append({
            'Cow Name': vac.cow.name,
            'Cow ID': vac.cow.cow_id,
            'Vaccine Name': vac.vaccine_name,
            'Vaccination Date': vac.vaccination_date.strftime('%Y-%m-%d'),
            'Next Due Date': vac.next_due_date.strftime('%Y-%m-%d') if vac.next_due_date else 'N/A',
            'Status': vac.status,
            'Notes': vac.notes,
            'Logged At': vac.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        })

    df = pd.DataFrame(data)
    output = io.BytesIO()
    writer = pd.ExcelWriter(output, engine='openpyxl')
    df.to_excel(writer, index=False, sheet_name='Vaccination History')
    writer.close()
    output.seek(0)

    return send_file(output, as_attachment=True, download_name=f'vaccination_history_{date.today().strftime("%Y%m%d")}.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

# ... (rest of your app.py code) ...

# if __name__ == '__main__':
#     app.run(debug=True)



