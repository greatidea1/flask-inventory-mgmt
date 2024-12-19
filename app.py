# app.py
from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username, password):
        self.id = id
        self.username = username
        self.password = password

def get_db():
    conn = sqlite3.connect('inventory.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    # Create admin user if not exists
    admin_exists = conn.execute('SELECT * FROM Users WHERE username = ?', ('admin',)).fetchone()
    if not admin_exists:
        password_hash = generate_password_hash('admin')
        conn.execute('INSERT INTO Users (username, password) VALUES (?, ?)', ('admin', password_hash))
        conn.commit()
    conn.close()

@login_manager.user_loader
def load_user(user_id):
    conn = get_db()
    user = conn.execute('SELECT * FROM Users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    if user:
        return User(user['id'], user['username'], user['password'])
    return None

@app.route('/')
def home():
    return render_template('login.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        user = conn.execute('SELECT * FROM Users WHERE username = ?', (username,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            user_obj = User(user['id'], user['username'], user['password'])
            login_user(user_obj)
            return redirect(url_for('dashboard'))
        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        if password != confirm_password:
            flash('Passwords do not match!')
            return render_template('register.html')
        
        password_hash = generate_password_hash(password)
        
        conn = get_db()
        try:
            conn.execute('INSERT INTO Users (username, password) VALUES (?, ?)', 
                        (username, password_hash))
            conn.commit()
            flash('Registration successful! Please login.')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username already exists')
        finally:
            conn.close()
    return render_template('register.html')

@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    results = []
    tables = ['Products', 'Customer', 'Supplier', 'Customer_Orders']
    selected_table = request.form.get('table', '')
    
    if request.method == 'POST':
        table = request.form['table']
        action = request.form.get('action', 'search')
        selected_table = table
        
        conn = get_db()
        if action == 'showall':
            # Show all records for the selected table
            if table == 'Products':
                results = conn.execute('SELECT * FROM Products').fetchall()
            elif table == 'Customer':
                results = conn.execute('SELECT * FROM Customer').fetchall()
            elif table == 'Supplier':
                results = conn.execute('SELECT * FROM Supplier').fetchall()
            elif table == 'Customer_Orders':
                results = conn.execute('''
                    SELECT co.order_id, c.name as customer_name, p.name as product_name,
                           co.quantity, co.order_date
                    FROM Customer_Orders co
                    JOIN Customer c ON co.customer_id = c.id
                    JOIN Products p ON co.product_id = p.id
                    ''').fetchall()
        else:
            # Existing search functionality
            search_term = request.form.get('search_term', '')
            if table == 'Products':
                results = conn.execute('''
                    SELECT * FROM Products 
                    WHERE name LIKE ? OR description LIKE ?
                    ''', (f'%{search_term}%', f'%{search_term}%')).fetchall()
            elif table == 'Customer':
                results = conn.execute('''
                    SELECT * FROM Customer 
                    WHERE name LIKE ? OR email LIKE ? OR phone LIKE ?
                    ''', (f'%{search_term}%', f'%{search_term}%', f'%{search_term}%')).fetchall()
            elif table == 'Supplier':
                results = conn.execute('''
                    SELECT * FROM Supplier 
                    WHERE name LIKE ? OR contact LIKE ? OR phone LIKE ?
                    ''', (f'%{search_term}%', f'%{search_term}%', f'%{search_term}%')).fetchall()
            elif table == 'Customer_Orders':
                results = conn.execute('''
                    SELECT co.order_id, c.name as customer_name, p.name as product_name,
                           co.quantity, co.order_date
                    FROM Customer_Orders co
                    JOIN Customer c ON co.customer_id = c.id
                    JOIN Products p ON co.product_id = p.id
                    WHERE c.name LIKE ? OR p.name LIKE ?
                    ''', (f'%{search_term}%', f'%{search_term}%')).fetchall()
        conn.close()
    
    return render_template('dashboard.html', 
                         results=results, 
                         tables=tables, 
                         selected_table=selected_table)

@app.route('/export_pdf')
@login_required
def export_pdf():
    conn = get_db()
    table = request.args.get('table', 'Products')
    
    # Get the data based on the table
    if table == 'Customer_Orders':
        results = conn.execute('''
            SELECT co.order_id, c.name as customer_name, p.name as product_name,
                   co.quantity, co.order_date
            FROM Customer_Orders co
            JOIN Customer c ON co.customer_id = c.id
            JOIN Products p ON co.product_id = p.id
        ''').fetchall()
    else:
        results = conn.execute(f'SELECT * FROM {table}').fetchall()
    
    # Get column names
    columns = [description[0] for description in conn.execute(f'SELECT * FROM {table} LIMIT 1').description]
    conn.close()

    # Create PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []

    # Add styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30,
        alignment=1
    )

    # Add title with timestamp
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
    title = Paragraph(f"{table} Report - {timestamp}", title_style)
    elements.append(title)

    # Prepare data for table
    data = [columns]  # Header row
    for row in results:
        # Convert all values to strings and handle None values
        data.append([str(value) if value is not None else '' for value in row])

    # Create table
    table = Table(data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 14),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 12),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
        ('TOPPADDING', (0, 1), (-1, -1), 8),
    ]))
    
    elements.append(table)
    
    # Build PDF
    doc.build(elements)
    buffer.seek(0)
    
    # Generate a safe filename
    safe_filename = f"{table}_report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    safe_filename = "".join(c for c in safe_filename if c.isalnum() or c in ('_', '-', '.'))
    
    try:
        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=safe_filename
        )
    except Exception as e:
        print(f"Error in send_file: {e}")
        # If there's an error, provide a simpler response
        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name='report.pdf'
        )

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))  

if __name__ == '__main__':
    init_db()  # Initialize admin user
    app.run(debug=True, host="0.0.0.0",port=3000)