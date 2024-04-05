import os, stripe, json, datetime
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, flash, request, abort, jsonify
from flask_bootstrap import Bootstrap
from .forms import LoginForm, RegisterForm
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, current_user, login_required, logout_user
from .db_models import db, User, Item
from itsdangerous import URLSafeTimedSerializer
from .funcs import mail, send_confirmation_email, fulfill_order
from dotenv import load_dotenv
from .admin.routes import admin
import pymysql
import boto3
import uuid
from botocore.config import Config
from app import controller as dynamodb
import requests
from .db_models import Order, Ordered_item, db, User
import requests

load_dotenv()
app = Flask(__name__)
app.register_blueprint(admin)

# app.config["SECRET_KEY"] = os.environ["SECRET_KEY"]
# app.config['SQLALCHEMY_DATABASE_URI'] = os.environ["DB_URI"]
# app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# app.config['MAIL_USERNAME'] = os.environ["EMAIL"]
# app.config['MAIL_PASSWORD'] = os.environ["PASSWORD"]
# app.config['MAIL_SERVER'] = "smtp.googlemail.com"
# app.config['MAIL_USE_TLS'] = True
# app.config['MAIL_PORT'] = 587
# stripe.api_key = os.environ["STRIPE_PRIVATE"]
# TODO: set up environment variables in the future
#


app.config["SECRET_KEY"] = "123" # TODO: research on what this secret key is for

app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://admin:12345678@rds-mysql-db.csxucthsan5l.ap-southeast-1.rds.amazonaws.com:3306/rds24emart'
# app.config['SQLALCHEMY_DATABASE_URI'] = "sqlite:///test.db"
#app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+mysqlconnector://root:@localhost:3306/24emart'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAIL_USERNAME'] = "randomemail@gmail.com" # not functional; TODO: create a dummy email
app.config['MAIL_PASSWORD'] = "123456" # not functional; TODO: create a dummy email
app.config['MAIL_SERVER'] = "smtp.googlemail.com"
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_PORT'] = 587
stripe.api_key = "sk_test_51MpZMRJRBOlt2OzTF2WW4p0GBJgEH3pZGmM2lrUejwjjQ0w3B2BeynxsWQbYVOIss5Nd8sexCy2NwQsLH7bZIxzW00ffqyZDP1" # TODO: set up stripe account


db.init_app(app)
Bootstrap(app)
mail.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)

with app.app_context():
	db.create_all()

@app.context_processor
def inject_now():
	""" sends datetime to templates as 'now' """
	return {'now': datetime.utcnow()}

@login_manager.user_loader
def load_user(user_id):
	return User.query.get(user_id)

S3_BUCKET = 'elasticbeanstalk-ap-southeast-1-645583429901'	
AWS_ACCESS_KEY_ID = 'AKIAZMT6FMEG2AH5MEF2'
AWS_SECRET_ACCESS_KEY = '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'
#s3 = boto3.client('s3', aws_access_key_id=AWS_ACCESS_KEY_ID, aws_secret_access_key=AWS_SECRET_ACCESS_KEY)
S3_REGION = 'ap-southeast-1'
S3_config = Config(signature_version='s3v4')

@app.route("/")
def home():
	items = Item.query.all()
	print(items)
	return render_template("home.html", items=items)

@app.route("/login", methods=['POST', 'GET'])
def login():
	if current_user.is_authenticated:
		return redirect(url_for('home'))
	form = LoginForm()
	if form.validate_on_submit():
		email = form.email.data
		user = User.query.filter_by(email=email).first()
		if user == None:
			flash(f'User with email {email} doesn\'t exist!<br> <a href={url_for("register")}>Register now!</a>', 'error')
			return redirect(url_for('login'))
		elif check_password_hash(user.password, form.password.data):
			login_user(user)
			return redirect(url_for('home'))
		else:
			flash("Email and password incorrect!!", "error")
			return redirect(url_for('login'))
	return render_template("login.html", form=form)

@app.route("/register", methods=['POST', 'GET'])
def register():
	if current_user.is_authenticated:
		return redirect(url_for('home'))
	form = RegisterForm()
	if form.validate_on_submit():
		user = User.query.filter_by(email=form.email.data).first()
		if user:
			flash(f"User with email {user.email} already exists!!<br> <a href={url_for('login')}>Login now!</a>", "error")
			return redirect(url_for('register'))
		hashed_password=generate_password_hash(
									form.password.data,
									method='pbkdf2:sha256',
									salt_length=8)
		new_user = User(name=form.name.data,
						email=form.email.data,
						password= hashed_password,
						phone=form.phone.data)
		db.session.add(new_user)
		db.session.commit()
		# write to dynamodb
		dynamodb.create_user(form.name.data, form.email.data, form.phone.data, hashed_password)   

		# send_confirmation_email(new_user.email)
		flash('Thanks for registering! You may login now.', 'success')
		return redirect(url_for('login'))
	return render_template("register.html", form=form)

@app.route('/profile', methods=['GET'])
@login_required
def profile():
	#print("Home page")
	#print(current_user.get_name())
	response = dynamodb.get_user(current_user.get_name())
	if (response['ResponseMetadata']['HTTPStatusCode'] ==200):
		if ('Item' in response):
			return render_template("userprofile.html", item = response['Item'])
		return {'msg': 'Item not found!'}
	return {
		'msg': 'error occurred',
		'response': response
	}



@app.route('/confirm/<token>')
def confirm_email(token):
	try:
		confirm_serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])
		email = confirm_serializer.loads(token, salt='email-confirmation-salt', max_age=3600)
	except:
		flash('The confirmation link is invalid or has expired.', 'error')
		return redirect(url_for('login'))
	user = User.query.filter_by(email=email).first()
	if user.email_confirmed:
		flash(f'Account already confirmed. Please login.', 'success')
	else:
		user.email_confirmed = True
		db.session.add(user)
		db.session.commit()
		flash('Email address successfully confirmed!', 'success')
	return redirect(url_for('login'))

@app.route("/logout")
@login_required
def logout():
	logout_user()
	return redirect(url_for('login'))

@app.route("/resend")
@login_required
def resend():
	send_confirmation_email(current_user.email)
	logout_user()
	flash('Confirmation email sent successfully.', 'success')
	return redirect(url_for('login'))

@app.route("/add/<id>", methods=['POST'])
def add_to_cart(id):
	if not current_user.is_authenticated:
		flash(f'You must login first!<br> <a href={url_for("login")}>Login now!</a>', 'error')
		return redirect(url_for('login'))

	item = Item.query.get(id)
	if request.method == "POST":
		quantity = request.form["quantity"]
		current_user.add_to_cart(id, quantity)
		flash(f'''{item.name} successfully added to the <a href=cart>cart</a>.<br> <a href={url_for("cart")}>view cart!</a>''','success')
		return redirect(url_for('home'))

@app.route("/cart")
@login_required
def cart():
	price = 0
	price_ids = []
	items = []
	quantity = []
	for cart in current_user.cart:
		items.append(cart.item)
		quantity.append(cart.quantity)
		price_id_dict = {
			"price": cart.item.price_id,
			"quantity": cart.quantity,
			}
		price_ids.append(price_id_dict)
		price += cart.item.price*cart.quantity
	return render_template('cart.html', items=items, price=price, price_ids=price_ids, quantity=quantity)

@app.route('/orders')
@login_required
def orders():
	return render_template('orders.html', orders=current_user.orders)

@app.route("/remove/<id>/<quantity>")
@login_required
def remove(id, quantity):
	current_user.remove_from_cart(id, quantity)
	return redirect(url_for('cart'))

@app.route('/item/<int:id>')
def item(id):
	item = Item.query.get(id)
	return render_template('item.html', item=item)

@app.route('/search')
def search():
	query = request.args['query']
	search = "%{}%".format(query)
	items = Item.query.filter(Item.name.like(search)).all()
	return render_template('home.html', items=items, search=True, query=query)

# stripe stuffs
@app.route('/payment_success')
def payment_success():
	return render_template('success.html')

@app.route('/payment_failure')
def payment_failure():
	return render_template('failure.html')

@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
	data = json.loads(request.form['price_ids'].replace("'", '"'))
	print(data)
	try:
		order = Order(uid=1, date=datetime.now(), status="processing")
		db.session.add(order)
		db.session.commit()

		current_user = User.query.get(1)
		for cart in current_user.cart:
			ordered_item = Ordered_item(oid=order.id, itemid=cart.item.id, quantity=cart.quantity)
			db.session.add(ordered_item)
			db.session.commit()
			current_user.remove_from_cart(cart.item.id, cart.quantity)
			db.session.commit()
		send_order_email()
		checkout_session = stripe.checkout.Session.create(
			client_reference_id=current_user.id,
			line_items=data,
			payment_method_types=[
			  'card',
			],
			mode='payment',
			success_url=url_for('payment_success', _external=True),
			cancel_url=url_for('payment_failure', _external=True),
		)
	except Exception as e:
		return str(e)
	return redirect(checkout_session.url, code=303)

@app.route('/webhook', methods=['POST'])
def webhook():

	if request.content_length > 1024*1024:
		print("Request too big!")
		abort(400)

	payload = request.get_data()
	sig_header = request.environ.get('HTTP_STRIPE_SIGNATURE')
	ENDPOINT_SECRET = "whsec_XaGKdX7hQGL8JqBpLj8bnuMBsPAQh1P1"
	event = None

	try:
		event = stripe.Webhook.construct_event(
		payload, sig_header, ENDPOINT_SECRET
		)
	except ValueError as e:
		# Invalid payload
		return {}, 400
	except stripe.error.SignatureVerificationError as e:
		# Invalid signature
		return {}, 400

	if event['type'] == 'checkout.session.completed':
		session = event['data']['object']
		# Fulfill the purchase...
		fulfill_order(session)

	# Passed signature verification
	return {}, 200


def send_order_email():
	# json = {
	# 	"email": current_user.email,
	# }
	api = "https://vonjfookj7.execute-api.ap-southeast-1.amazonaws.com/test/confirmorderlambdases"
	data = {
		"email": "noreply.24emart@gmail.com"
	}
	try:
		response = requests.post(api, json = data)
		if response.status_code == 200:
			return ("A confirmation email on your successful order has been sent to your email")
	except Exception as e:
		return str(e)
		# print(f"Sorry, there's a {response.status_code} error with sending the email request.")