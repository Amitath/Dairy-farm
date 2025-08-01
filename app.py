# app.py
import os

from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from models import db, Cow, MilkProduction, HealthRecord, Customer, Sale, Payment, Expense
from datetime import date, datetime
from sqlalchemy import func, extract
from config import Config
import click
import pandas as pd # <--- Import pandas
import io
app = Flask(__name__)

# --- Database Configuration ---
# Replace with your PostgreSQL credentials
app.config.from_object(Config)

db.init_app(app)
# --- Context Processor ---
# This makes 'today' and 'now' available in ALL your templates
@app.context_processor
def inject_common_variables(): # Renamed from inject_today for clarity, but old name works too
    return {
        'today': date.today(),
        'now': datetime.now # <--- ADD THIS LINE
    }

# --- Flask CLI Custom Commands ---
@app.cli.command("create-db")
def create_db_command():
    """Creates the database tables."""
    instance_path = os.path.join(app.root_path, 'instance')
    if not os.path.exists(instance_path):
        os.makedirs(instance_path)
        click.echo(f"Created instance directory: {instance_path}")
    db.create_all()
    click.echo("Database tables created!")

# --- Routes ---
# --- Routes ---
@app.route('/')
def index():
    total_cows = Cow.query.count()
    active_cows = Cow.query.filter_by(status='active').count()

    today_date = date.today()
    today_milk_records = MilkProduction.query.filter_by(date=today_date).all()
    total_today_milk = sum(rec.total_daily_quantity() for rec in today_milk_records)

    total_receivable = db.session.query(func.sum(Customer.balance)).scalar() or 0.0

    recent_sales = Sale.query.order_by(Sale.timestamp.desc()).limit(5).all()
    recent_expenses = Expense.query.order_by(Expense.timestamp.desc()).limit(5).all()

    return render_template('index.html',
                           total_cows=total_cows,
                           active_cows=active_cows,
                           total_today_milk=total_today_milk,
                           total_receivable=total_receivable,
                           recent_sales=recent_sales,
                           recent_expenses=recent_expenses)

# --- Cow Management ---
@app.route('/cows')
def view_cows():
    cows = Cow.query.all()
    return render_template('view_cows.html', cows=cows)

@app.route('/cows/add', methods=['GET', 'POST'])
def add_cow():
    if request.method == 'POST':
        cow_id = request.form['cow_id']
        name = request.form['name']
        breed = request.form.get('breed')
        date_of_birth_str = request.form.get('date_of_birth')

        date_of_birth = None
        if date_of_birth_str:
            try:
                date_of_birth = datetime.strptime(date_of_birth_str, '%Y-%m-%d').date()
            except ValueError:
                flash("Invalid date format for Date of Birth. Please use YYYY-MM-DD.", 'danger')
                return render_template('add_cow.html')

        existing_cow = Cow.query.filter_by(cow_id=cow_id).first()
        if existing_cow:
            flash(f"Cow ID '{cow_id}' already exists. Please use a unique ID.", 'danger')
            return render_template('add_cow.html', cow_id=cow_id, name=name, breed=breed, date_of_birth=date_of_birth_str)


        new_cow = Cow(cow_id=cow_id, name=name, breed=breed, date_of_birth=date_of_birth)
        try:
            db.session.add(new_cow)
            db.session.commit()
            flash(f'Cow "{name}" ({cow_id}) added successfully!', 'success')
            return redirect(url_for('view_cows'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding cow: {str(e)}', 'danger')
    return render_template('add_cow.html')

# --- Milk Production ---
@app.route('/milk_production/log', methods=['GET', 'POST'])
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
            return render_template('log_milk_production.html', cows=cows)

        try:
            log_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD.", 'danger')
            return render_template('log_milk_production.html', cows=cows)

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
def milk_history():
    milk_records = MilkProduction.query.order_by(MilkProduction.date.desc(), MilkProduction.timestamp.desc()).all()
    return render_template('milk_history.html', milk_records=milk_records)

# --- Health Records ---
@app.route('/health_records/add', methods=['GET', 'POST'])
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
            return render_template('add_health_record.html', cows=cows)

        try:
            record_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD.", 'danger')
            return render_template('add_health_record.html', cows=cows)

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
def view_health_records():
    health_records = HealthRecord.query.order_by(HealthRecord.date.desc(), HealthRecord.timestamp.desc()).all()
    return render_template('view_health_records.html', health_records=health_records)

# --- Customer Management ---
@app.route('/customers')
def view_customers():
    customers = Customer.query.order_by(Customer.name).all()
    return render_template('view_customers.html', customers=customers)

@app.route('/customers/add', methods=['GET', 'POST'])
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

# --- Sales ---
@app.route('/sales/record', methods=['GET', 'POST'])
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
            return render_template('record_sale.html', customers=customers)

        try:
            sale_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD.", 'danger')
            return render_template('record_sale.html', customers=customers)

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
            # Update customer's balance
            customer.balance += total_amount
            db.session.commit()
            flash(f'Sale to {customer.name} recorded successfully! Amount: {total_amount:.2f}', 'success')
            return redirect(url_for('view_sales'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error recording sale: {str(e)}', 'danger')
    return render_template('record_sale.html', customers=customers)

@app.route('/sales')
def view_sales():
    sales = Sale.query.order_by(Sale.date.desc(), Sale.timestamp.desc()).all()
    return render_template('view_sales.html', sales=sales)

# --- Payments ---
@app.route('/payments/record', methods=['GET', 'POST'])
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
            return render_template('record_payment.html', customers=customers)

        try:
            payment_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD.", 'danger')
            return render_template('record_payment.html', customers=customers)

        new_payment = Payment(
            customer_id=customer.id,
            date=payment_date,
            amount_received=amount_received,
            description=description
        )
        try:
            db.session.add(new_payment)
            # Update customer's balance
            customer.balance -= amount_received
            db.session.commit()
            flash(f'Payment from {customer.name} recorded successfully! Amount: {amount_received:.2f}', 'success')
            return redirect(url_for('view_payments'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error recording payment: {str(e)}', 'danger')
    return render_template('record_payment.html', customers=customers)

@app.route('/payments')
def view_payments():
    payments = Payment.query.order_by(Payment.date.desc(), Payment.timestamp.desc()).all()
    return render_template('view_payments.html', payments=payments)

# --- Expenses ---
@app.route('/expenses/record', methods=['GET', 'POST'])
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
            return render_template('record_expense.html')

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
def view_expenses():
    expenses = Expense.query.order_by(Expense.date.desc(), Expense.timestamp.desc()).all()
    return render_template('view_expenses.html', expenses=expenses)

# --- Reports ---
@app.route('/profit_loss', methods=['GET', 'POST'])
def profit_loss():
    start_date = None
    end_date = None
    total_income = 0.0
    total_expenses = 0.0
    net_profit_loss = 0.0
    transactions = [] # To display relevant transactions

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

        # Calculate Income (Sales)
        sales_query = db.session.query(func.sum(Sale.total_amount))
        if start_date:
            sales_query = sales_query.filter(Sale.date >= start_date)
        if end_date:
            sales_query = sales_query.filter(Sale.date <= end_date)
        total_income = sales_query.scalar() or 0.0

        # Calculate Expenses
        expenses_query = db.session.query(func.sum(Expense.amount))
        if start_date:
            expenses_query = expenses_query.filter(Expense.date >= start_date)
        if end_date:
            expenses_query = expenses_query.filter(Expense.date <= end_date)
        total_expenses = expenses_query.scalar() or 0.0

        net_profit_loss = total_income - total_expenses

        # Fetch relevant sales and expenses for detailed view
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
        transactions.sort(key=lambda x: x.date, reverse=True) # Sort by date

    return render_template('profit_loss.html',
                           start_date=start_date,
                           end_date=end_date,
                           total_income=total_income,
                           total_expenses=total_expenses,
                           net_profit_loss=net_profit_loss,
                           transactions=transactions)


@app.route('/amounts_receivable')
def amounts_receivable():
    # Customers with a positive balance (they owe you)
    customers_owing = Customer.query.filter(Customer.balance > 0).order_by(Customer.name).all()
    return render_template('amounts_receivable.html', customers_owing=customers_owing)


# --- Database Initialization (Run once) ---
@app.route('/init_db')
def init_db():
    with app.app_context():
        # This creates the 'instance' folder if it doesn't exist
        instance_path = os.path.join(app.root_path, 'instance')
        if not os.path.exists(instance_path):
            os.makedirs(instance_path)
            print(f"Created instance directory: {instance_path}") # Optional: for confirmation

        # This creates all the tables defined in your models.py
        db.create_all()
        print("Database tables created successfully!")  # Add this for confirmation
    return "Database tables created!"

# --- EXPORT ROUTES ---

@app.route('/export/milk_production')
def export_milk_production():
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
    writer.close() # Use writer.close() instead of writer.save() for newer pandas
    output.seek(0)

    return send_file(output, as_attachment=True, download_name=f'milk_production_{date.today().strftime("%Y%m%d")}.xlsx', mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.route('/export/health_records')
def export_health_records():
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
def export_sales():
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
def export_payments():
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
def export_expenses():
    expenses = Expense.query.all()
    data = []
    for record in expenses:
        data.append({
            'Date': record.date.strftime('%Y-%m-%d'),
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

# --- Run the application ---
if __name__ == '__main__':
    # Make sure this block is COMMENTED OUT. You should use the /init_db route.
    # with app.app_context():
    #     instance_path = os.path.join(app.root_path, 'instance')
    #     if not os.path.exists(instance_path):
    #         os.makedirs(instance_path)
    #         print(f"Created instance directory: {instance_path}")
    #     db.create_all()

    app.run(debug=True) # debug=True allows auto-reloading and better error messages