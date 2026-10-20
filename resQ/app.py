import os
import math
import json
import uuid
import threading
import time
import secrets
import click
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest, urlopen

from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

is_vercel = os.getenv("VERCEL", "").strip().lower() in {"1", "true"}
database_url = os.getenv("DATABASE_URL")
if not database_url:
    if is_vercel:
        raise RuntimeError("DATABASE_URL must be configured for the Vercel deployment.")
    database_url = "sqlite:///resq.db"

try:
    parsed_database_url = make_url(database_url)
except SQLAlchemyError:
    raise RuntimeError("DATABASE_URL is not a valid SQLAlchemy database URL.") from None

if parsed_database_url.drivername == "postgres":
    parsed_database_url = parsed_database_url.set(drivername="postgresql")

if parsed_database_url.get_backend_name() == "postgresql":
    if parsed_database_url.drivername in {"postgresql", "postgresql+psycopg2"}:
        parsed_database_url = parsed_database_url.set(drivername="postgresql+psycopg")

if is_vercel and parsed_database_url.get_backend_name() != "postgresql":
    raise RuntimeError("DATABASE_URL must point to PostgreSQL in the Vercel deployment.")

if parsed_database_url.get_backend_name() == "postgresql":
    postgres_options = dict(parsed_database_url.query)
    postgres_options.setdefault("sslmode", "require")
    parsed_database_url = parsed_database_url.set(query=postgres_options)

app = Flask(__name__)
secret_key = os.getenv("SECRET_KEY")
if is_vercel and not secret_key:
    raise RuntimeError("SECRET_KEY must be configured for the Vercel deployment.")
app.config["SECRET_KEY"] = secret_key or secrets.token_urlsafe(32)
app.config["SQLALCHEMY_DATABASE_URI"] = parsed_database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
if parsed_database_url.get_backend_name() == "postgresql":
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }


db = SQLAlchemy(app)

NEARBY_HOSPITALS_CACHE = {}
NOMINATIM_REQUEST_LOCK = threading.Lock()
NOMINATIM_LAST_REQUEST = 0.0


def utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def nominatim_json(url, timeout=12):
    global NOMINATIM_LAST_REQUEST
    with NOMINATIM_REQUEST_LOCK:
        wait_seconds = 1.1 - (time.monotonic() - NOMINATIM_LAST_REQUEST)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        NOMINATIM_LAST_REQUEST = time.monotonic()

    geocoder_request = UrlRequest(
        url,
        headers={
            "User-Agent": "ResQ-Emergency-Prototype/1.0",
            "Accept": "application/json",
        },
    )
    with urlopen(geocoder_request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow_naive)


class AmbulanceProvider(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    provider_name = db.Column(db.String(160), nullable=False)
    contact_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    registration_number = db.Column(db.String(80), nullable=False)
    ambulance_type = db.Column(db.String(80), nullable=False)
    service_area = db.Column(db.String(160), nullable=False)
    current_location = db.Column(db.String(200), default="")
    latitude = db.Column(db.Float, default=0.0)
    longitude = db.Column(db.Float, default=0.0)
    verification_status = db.Column(db.String(30), default="PENDING")
    availability_status = db.Column(db.String(30), default="AVAILABLE")
    created_at = db.Column(db.DateTime, default=utcnow_naive)


class ShelterProvider(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    shelter_name = db.Column(db.String(160), nullable=False)
    contact_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    address = db.Column(db.String(200), nullable=False)
    latitude = db.Column(db.Float, default=0.0)
    longitude = db.Column(db.Float, default=0.0)
    service_area = db.Column(db.String(160), default="")
    total_capacity = db.Column(db.Integer, default=0)
    occupied_spaces = db.Column(db.Integer, default=0)
    available_spaces = db.Column(db.Integer, default=0)
    facilities = db.Column(db.String(200), default="")
    verification_status = db.Column(db.String(30), default="PENDING")
    availability_status = db.Column(db.String(30), default="AVAILABLE")
    created_at = db.Column(db.DateTime, default=utcnow_naive)


class Volunteer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    skills = db.Column(db.String(250), default="")
    service_area = db.Column(db.String(160), default="")
    availability = db.Column(db.String(30), default="AVAILABLE")
    latitude = db.Column(db.Float, default=0.0)
    longitude = db.Column(db.Float, default=0.0)
    verification_status = db.Column(db.String(30), default="PENDING")
    created_at = db.Column(db.DateTime, default=utcnow_naive)


class Hospital(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    address = db.Column(db.String(200), nullable=False)
    latitude = db.Column(db.Float, default=0.0)
    longitude = db.Column(db.Float, default=0.0)
    phone = db.Column(db.String(20), default="")
    emergency_contact = db.Column(db.String(20), default="")
    facilities = db.Column(db.String(200), default="")
    total_beds = db.Column(db.Integer, default=0)
    occupied_beds = db.Column(db.Integer, default=0)
    available_beds = db.Column(db.Integer, default=0)
    verification_status = db.Column(db.String(30), default="PENDING")
    updated_at = db.Column(db.DateTime, default=utcnow_naive)


class BloodDonor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    blood_group = db.Column(db.String(10), nullable=False)
    city = db.Column(db.String(100), default="")
    preferred_location = db.Column(db.String(200), default="")
    availability_status = db.Column(db.String(30), default="AVAILABLE")
    consent = db.Column(db.Boolean, default=True)
    verification_status = db.Column(db.String(30), default="PENDING")
    created_at = db.Column(db.DateTime, default=utcnow_naive)


class EmergencyRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    emergency_id = db.Column(db.String(40), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    problem_description = db.Column(db.Text, nullable=False)
    people_affected = db.Column(db.Integer, default=1)
    required_assistance = db.Column(db.String(200), default="")
    current_location = db.Column(db.String(200), default="")
    latitude = db.Column(db.Float, default=0.0)
    longitude = db.Column(db.Float, default=0.0)
    preferred_hospital = db.Column(db.String(200), default="")
    blood_required = db.Column(db.Boolean, default=False)
    blood_group = db.Column(db.String(10), default="")
    additional_info = db.Column(db.Text, default="")
    status = db.Column(db.String(50), default="PENDING")
    priority = db.Column(db.String(40), default="Medium")
    ai_recommendation = db.Column(db.Text, default="")
    ai_explanation = db.Column(db.Text, default="")
    assigned_ambulance_id = db.Column(db.Integer, nullable=True)
    assigned_shelter_id = db.Column(db.Integer, nullable=True)
    assigned_volunteer_id = db.Column(db.Integer, nullable=True)
    assigned_hospital_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)


class BloodRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_name = db.Column(db.String(120), nullable=False)
    blood_group = db.Column(db.String(10), nullable=False)
    location = db.Column(db.String(200), default="")
    urgency = db.Column(db.String(30), default="High")
    status = db.Column(db.String(30), default="PENDING")
    created_at = db.Column(db.DateTime, default=utcnow_naive)


class ResourceAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    emergency_request_id = db.Column(db.Integer, db.ForeignKey("emergency_request.id"), nullable=False)
    ambulance_id = db.Column(db.Integer, nullable=True)
    shelter_id = db.Column(db.Integer, nullable=True)
    volunteer_id = db.Column(db.Integer, nullable=True)
    hospital_id = db.Column(db.Integer, nullable=True)
    status = db.Column(db.String(50), default="ASSIGNED")
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=utcnow_naive)


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(80), default="SYSTEM")
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    target_role = db.Column(db.String(50), default="ADMIN")
    target_id = db.Column(db.Integer, nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow_naive)


class StatusHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    emergency_request_id = db.Column(db.Integer, db.ForeignKey("emergency_request.id"), nullable=False)
    previous_status = db.Column(db.String(50), default="")
    new_status = db.Column(db.String(50), nullable=False)
    changed_by = db.Column(db.String(50), default="SYSTEM")
    reason = db.Column(db.String(200), default="")
    created_at = db.Column(db.DateTime, default=utcnow_naive)


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(200), nullable=False)
    actor_type = db.Column(db.String(60), default="SYSTEM")
    actor_id = db.Column(db.Integer, nullable=True)
    details = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=utcnow_naive)


EMERGENCY_CATEGORIES = [
    "Medical emergency",
    "Road accident",
    "Fire",
    "Flood",
    "Trapped person",
    "Missing person",
    "Shelter requirement",
    "Blood requirement",
    "Food and water requirement",
    "Other emergency",
]

BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]


def ambulance_is_required(assistance):
    return "ambulance" in (assistance or "").casefold()


def create_seed_data():
    if Admin.query.first():
        return

    admin = Admin(
        name="System Administrator",
        email=os.getenv("ADMIN_EMAIL", "zakeerabdul@admin.com"),
        password_hash=generate_password_hash(os.getenv("ADMIN_PASSWORD", "admin@123")),
    )
    db.session.add(admin)

    ambulance1 = AmbulanceProvider(
        provider_name="FastLife EMS",
        contact_name="Ravi Kumar",
        email="ravi@fastlifeems.com",
        password_hash=generate_password_hash("pass123"),
        phone="9876543210",
        registration_number="AP12-EM-9087",
        ambulance_type="Advanced Life Support",
        service_area="Downtown",
        current_location="City General Area",
        latitude=17.4401,
        longitude=78.4882,
        verification_status="VERIFIED",
        availability_status="AVAILABLE",
    )
    ambulance2 = AmbulanceProvider(
        provider_name="CityCare Rescue",
        contact_name="Narendra Rao",
        email="narendra@citycarerescue.com",
        password_hash=generate_password_hash("pass123"),
        phone="9876543211",
        registration_number="TS09-RT-7651",
        ambulance_type="Basic Life Support",
        service_area="Old City",
        current_location="Old City Hub",
        latitude=17.4278,
        longitude=78.4853,
        verification_status="VERIFIED",
        availability_status="BUSY",
    )
    ambulance3 = AmbulanceProvider(
        provider_name="Rapid Response Unit",
        contact_name="Asha Reddy",
        email="asha@rapidresponse.com",
        password_hash=generate_password_hash("pass123"),
        phone="9876543212",
        registration_number="TG03-AR-1014",
        ambulance_type="Critical Care",
        service_area="West Zone",
        current_location="Banjara Hills",
        latitude=17.4120,
        longitude=78.4072,
        verification_status="VERIFIED",
        availability_status="AVAILABLE",
    )
    db.session.add_all([ambulance1, ambulance2, ambulance3])

    shelter1 = ShelterProvider(
        shelter_name="Hope Haven Shelter",
        contact_name="Sonia Verma",
        email="sonia@hopehaven.com",
        password_hash=generate_password_hash("pass123"),
        phone="9876543213",
        address="MG Road, Hyderabad",
        latitude=17.4367,
        longitude=78.4747,
        service_area="Central Hyderabad",
        total_capacity=80,
        occupied_spaces=32,
        available_spaces=48,
        facilities="Medical support, cots, food, security",
        verification_status="VERIFIED",
        availability_status="AVAILABLE",
    )
    shelter2 = ShelterProvider(
        shelter_name="Sunrise Safe House",
        contact_name="Karthik Rao",
        email="karthik@sunrisesafehouse.com",
        password_hash=generate_password_hash("pass123"),
        phone="9876543214",
        address="Kondapur, Hyderabad",
        latitude=17.4565,
        longitude=78.3599,
        service_area="South Hyderabad",
        total_capacity=60,
        occupied_spaces=58,
        available_spaces=2,
        facilities="Blankets, water, family rooms, CCTV",
        verification_status="VERIFIED",
        availability_status="BUSY",
    )
    db.session.add_all([shelter1, shelter2])

    volunteer1 = Volunteer(
        name="Meghana Iyer",
        email="meghana@resq.com",
        password_hash=generate_password_hash("pass123"),
        phone="9876543215",
        skills="First aid, evacuations, food distribution",
        service_area="Central Hyderabad",
        availability="AVAILABLE",
        latitude=17.4305,
        longitude=78.4814,
        verification_status="VERIFIED",
    )
    volunteer2 = Volunteer(
        name="Praveen Kumar",
        email="praveen@resq.com",
        password_hash=generate_password_hash("pass123"),
        phone="9876543216",
        skills="Medical assistance, transport coordination",
        service_area="Secunderabad",
        availability="BUSY",
        latitude=17.4419,
        longitude=78.4871,
        verification_status="VERIFIED",
    )
    db.session.add_all([volunteer1, volunteer2])

    hospital1 = Hospital(
        name="City General Hospital",
        address="Abids, Hyderabad",
        latitude=17.3988,
        longitude=78.4894,
        phone="040-22334455",
        emergency_contact="040-22334456",
        facilities="ICU, trauma, emergency",
        total_beds=350,
        occupied_beds=180,
        available_beds=170,
        verification_status="VERIFIED",
        updated_at=utcnow_naive(),
    )
    hospital2 = Hospital(
        name="CarePlus Multispecialty",
        address="Madhapur, Hyderabad",
        latitude=17.4404,
        longitude=78.3918,
        phone="040-33445566",
        emergency_contact="040-33445567",
        facilities="ICU, maternity, trauma",
        total_beds=250,
        occupied_beds=200,
        available_beds=50,
        verification_status="VERIFIED",
        updated_at=utcnow_naive(),
    )
    hospital3 = Hospital(
        name="Rural Health Center",
        address="Gachibowli, Hyderabad",
        latitude=17.4413,
        longitude=78.3523,
        phone="040-44556677",
        emergency_contact="040-44556678",
        facilities="Emergency, surgery",
        total_beds=150,
        occupied_beds=145,
        available_beds=5,
        verification_status="VERIFIED",
        updated_at=utcnow_naive(),
    )
    db.session.add_all([hospital1, hospital2, hospital3])

    donor1 = BloodDonor(
        name="Anjali Nair",
        email="anjali@donor.com",
        password_hash=generate_password_hash("pass123"),
        phone="9876543217",
        blood_group="O+",
        city="Hyderabad",
        preferred_location="City General",
        availability_status="AVAILABLE",
        consent=True,
        verification_status="VERIFIED",
    )
    donor2 = BloodDonor(
        name="Suresh Babu",
        email="suresh@donor.com",
        password_hash=generate_password_hash("pass123"),
        phone="9876543218",
        blood_group="A+",
        city="Hyderabad",
        preferred_location="Madhapur",
        availability_status="AVAILABLE",
        consent=True,
        verification_status="VERIFIED",
    )
    db.session.add_all([donor1, donor2])

    req1 = EmergencyRequest(
        emergency_id="RQ-1001",
        name="Uma Rani",
        phone="9988776655",
        category="Medical emergency",
        problem_description="Severe chest pain and breathing difficulty after exertion.",
        people_affected=1,
        required_assistance="Ambulance and hospital transfer",
        current_location="Abids, Hyderabad",
        latitude=17.3977,
        longitude=78.4871,
        preferred_hospital="City General Hospital",
        blood_required=False,
        status="RESOURCE_ASSIGNED",
        priority="High",
        ai_recommendation="Critical",
        ai_explanation="Severe cardiac symptoms require urgent transport and emergency evaluation.",
        assigned_ambulance_id=1,
        assigned_hospital_id=1,
    )
    req2 = EmergencyRequest(
        emergency_id="RQ-1002",
        name="Kiran Rao",
        phone="9988776656",
        category="Road accident",
        problem_description="Two passengers injured after a collision near a flyover.",
        people_affected=2,
        required_assistance="Ambulance and trauma care",
        current_location="Madhapur Flyover",
        latitude=17.4398,
        longitude=78.3902,
        preferred_hospital="CarePlus Multispecialty",
        blood_required=False,
        status="PENDING",
        priority="High",
        ai_recommendation="High",
        ai_explanation="Multiple injury mechanism warrants rapid assessment and trauma support.",
    )
    db.session.add_all([req1, req2])

    db.session.commit()

    for req in [req1, req2]:
        db.session.add(StatusHistory(emergency_request_id=req.id, previous_status="PENDING", new_status=req.status, changed_by="SYSTEM", reason="Seeded demo data"))

    db.session.add(Notification(category="EMERGENCY", title="Emergency request received", message="New emergency request RQ-1002 received for review.", target_role="ADMIN"))
    db.session.add(Notification(category="RESOURCE", title="Ambulance accepted", message="Ambulance FastLife EMS accepted emergency RQ-1001.", target_role="ADMIN"))
    db.session.add(BloodRequest(patient_name="Sarita", blood_group="O-", location="Secunderabad", urgency="High", status="PENDING"))
    db.session.commit()


@app.route("/")
def index():
    emergency_count = EmergencyRequest.query.count()
    active_ambulances = AmbulanceProvider.query.filter_by(availability_status="AVAILABLE").count()
    available_shelters = ShelterProvider.query.filter_by(availability_status="AVAILABLE").count()
    hospitals = Hospital.query.count()
    donors = BloodDonor.query.count()
    pending_requests = EmergencyRequest.query.filter_by(status="PENDING").count()
    return render_template(
        "index.html",
        emergency_count=emergency_count,
        active_ambulances=active_ambulances,
        available_shelters=available_shelters,
        hospitals=hospitals,
        donors=donors,
        pending_requests=pending_requests,
    )


@app.route("/emergency-help")
def emergency_help():
    return render_template(
        "emergency_form.html",
        categories=EMERGENCY_CATEGORIES,
        blood_groups=BLOOD_GROUPS,
    )


@app.route("/submit-emergency", methods=["POST"])
def submit_emergency():
    required = ["name", "phone", "category", "problem_description"]
    for field in required:
        if not request.form.get(field, "").strip():
            flash("Please complete the required emergency details.", "error")
            return redirect(url_for("emergency_help"))

    blood_group = request.form.get("blood_group", "").strip()
    if blood_group and blood_group not in BLOOD_GROUPS:
        flash("Please select a valid blood group.", "error")
        return redirect(url_for("emergency_help"))

    request_data = {
        "name": request.form.get("name").strip(),
        "phone": request.form.get("phone").strip(),
        "category": request.form.get("category").strip(),
        "problem_description": request.form.get("problem_description").strip(),
        "people_affected": int(request.form.get("people_affected", 1) or 1),
        "required_assistance": request.form.get("required_assistance", "").strip(),
        "current_location": request.form.get("current_location", "").strip(),
        "latitude": float(request.form.get("latitude", 0.0) or 0.0),
        "longitude": float(request.form.get("longitude", 0.0) or 0.0),
        "blood_required": request.form.get("blood_required") == "on",
        "blood_group": blood_group,
        "additional_info": request.form.get("additional_info", "").strip(),
        "status": "PENDING",
        "priority": "Medium",
        "ai_recommendation": "Pending review",
        "ai_explanation": "Rule-based triage placeholder. Human review remains required.",
    }

    emergency_id = f"RQ-{uuid.uuid4().hex.upper()}"
    try:
        while EmergencyRequest.query.filter_by(emergency_id=emergency_id).first():
            emergency_id = f"RQ-{uuid.uuid4().hex.upper()}"

        emergency = EmergencyRequest(emergency_id=emergency_id, **request_data)
        db.session.add(emergency)
        db.session.flush()
        db.session.add(StatusHistory(
            emergency_request_id=emergency.id,
            previous_status="NEW",
            new_status="PENDING",
            changed_by="SYSTEM",
            reason="Emergency request submitted",
        ))

        ambulance_required = ambulance_is_required(emergency.required_assistance)
        admin_message = f"Emergency {emergency_id} has been received and is awaiting admin review."
        if ambulance_required:
            admin_message += " An ambulance was requested and the request is available to ambulance providers."
            db.session.add(Notification(
                category="EMERGENCY",
                title="Ambulance requested",
                message=f"Emergency {emergency_id} requires an ambulance. Review it in Emergency Monitoring.",
                target_role="AMBULANCE",
            ))
        db.session.add(Notification(
            category="EMERGENCY",
            title="New emergency request",
            message=admin_message,
            target_role="ADMIN",
        ))
        db.session.commit()
    except SQLAlchemyError as error:
        db.session.rollback()
        app.logger.error(
            "Failed to save emergency submission (database error: %s).",
            type(error).__name__,
        )
        flash("We couldn't save your emergency request. Please try again.", "error")
        return redirect(url_for("emergency_help"))

    flash(f"Emergency request {emergency_id} received.", "success")
    return redirect(url_for("emergency_confirmation", emergency_id=emergency_id))


@app.route("/emergency-confirmation/<emergency_id>")
def emergency_confirmation(emergency_id):
    emergency = EmergencyRequest.query.filter_by(emergency_id=emergency_id).first_or_404()
    return render_template("emergency_confirmation.html", emergency=emergency)


@app.route("/api/emergency-location/<emergency_id>", methods=["POST"])
def update_emergency_location(emergency_id):
    emergency = EmergencyRequest.query.filter_by(emergency_id=emergency_id).first_or_404()
    if emergency.status in {"RESOLVED", "CANCELLED"}:
        return jsonify({"error": "Location sharing is closed for this request."}), 409

    location = request.get_json()
    try:
        latitude = float(location.get("latitude"))
        longitude = float(location.get("longitude"))
    except (AttributeError, TypeError, ValueError):
        return jsonify({"error": "Valid latitude and longitude are required."}), 400

    if not (math.isfinite(latitude) and math.isfinite(longitude)
            and -90 <= latitude <= 90 and -180 <= longitude <= 180):
        return jsonify({"error": "Coordinates are outside the valid range."}), 400

    emergency.latitude = latitude
    emergency.longitude = longitude
    db.session.commit()
    return jsonify({"status": "updated"})


@app.route("/request-tracking", methods=["GET", "POST"])
def request_tracking():
    emergency = None
    if request.method == "POST":
        emergency_id = request.form.get("emergency_id", "").strip()
        emergency = EmergencyRequest.query.filter_by(emergency_id=emergency_id).first()
        if not emergency:
            flash("No request was found with that emergency ID.", "error")
    return render_template("track_request.html", emergency=emergency)


@app.route("/api/request-tracking/<emergency_id>")
def api_request_tracking(emergency_id):
    emergency = EmergencyRequest.query.filter_by(emergency_id=emergency_id).first_or_404()
    has_coordinates = (
        math.isfinite(emergency.latitude)
        and math.isfinite(emergency.longitude)
        and -90 <= emergency.latitude <= 90
        and -180 <= emergency.longitude <= 180
        and (emergency.latitude != 0 or emergency.longitude != 0)
    )
    return jsonify({
        "emergency_id": emergency.emergency_id,
        "status": emergency.status,
        "location": emergency.current_location,
        "latitude": emergency.latitude if has_coordinates else None,
        "longitude": emergency.longitude if has_coordinates else None,
        "updated_at": emergency.updated_at.isoformat() + "Z" if emergency.updated_at else None,
        "location_sharing_available": emergency.status not in {"RESOLVED", "CANCELLED"},
    })


@app.route("/admin-login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        admin = Admin.query.filter_by(email=email).first()
        if admin and check_password_hash(admin.password_hash, password):
            session["role"] = "admin"
            session["user_id"] = admin.id
            session["user_name"] = admin.name
            flash("Welcome back, administrator.", "success")
            return redirect(url_for("admin_dashboard"))
        flash("Invalid administrator credentials.", "error")
    return render_template("admin_login.html")


@app.route("/admin-logout")
def admin_logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("admin_login"))


@app.route("/admin/dashboard")
def admin_dashboard():
    if not require_role("admin"):
        return redirect(url_for("admin_login"))
    stats = {
        "total_requests": EmergencyRequest.query.count(),
        "pending_requests": EmergencyRequest.query.filter_by(status="PENDING").count(),
        "high_priority": EmergencyRequest.query.filter_by(priority="High").count(),
        "assigned": EmergencyRequest.query.filter(EmergencyRequest.status.in_(["RESOURCE_ASSIGNED", "ACCEPTED", "EN_ROUTE", "ARRIVED", "IN_PROGRESS"])).count(),
        "active_ambulances": AmbulanceProvider.query.filter_by(availability_status="AVAILABLE").count(),
        "busy_ambulances": AmbulanceProvider.query.filter_by(availability_status="BUSY").count(),
        "available_shelters": ShelterProvider.query.filter_by(availability_status="AVAILABLE").count(),
        "available_volunteers": Volunteer.query.filter_by(availability="AVAILABLE").count(),
        "registered_hospitals": Hospital.query.count(),
        "available_beds": sum(h.available_beds for h in Hospital.query.all()),
        "pending_blood": BloodRequest.query.filter_by(status="PENDING").count(),
        "resolved": EmergencyRequest.query.filter_by(status="RESOLVED").count(),
    }
    recent = EmergencyRequest.query.order_by(EmergencyRequest.created_at.desc()).limit(5).all()
    return render_template("admin_dashboard.html", stats=stats, recent=recent)


@app.route("/admin/monitoring")
def admin_monitoring():
    if not require_role("admin"):
        return redirect(url_for("admin_login"))
    items = EmergencyRequest.query.order_by(EmergencyRequest.created_at.desc()).all()
    return render_template("admin_monitoring.html", requests=items)


@app.route("/admin/map")
def admin_map():
    if not require_role("admin"):
        return redirect(url_for("admin_login"))
    return render_template("admin_map.html")


@app.route("/admin/providers")
def admin_providers():
    if not require_role("admin"):
        return redirect(url_for("admin_login"))
    ambulances = AmbulanceProvider.query.all()
    shelters = ShelterProvider.query.all()
    volunteers = Volunteer.query.all()
    hospitals = Hospital.query.all()
    donors = BloodDonor.query.all()
    return render_template(
        "admin_providers.html",
        ambulances=ambulances,
        shelters=shelters,
        volunteers=volunteers,
        hospitals=hospitals,
        donors=donors,
    )


@app.route("/admin/reports")
def admin_reports():
    if not require_role("admin"):
        return redirect(url_for("admin_login"))
    category_counts = db.session.query(EmergencyRequest.category, func.count(EmergencyRequest.id)).group_by(EmergencyRequest.category).all()
    status_counts = db.session.query(EmergencyRequest.status, func.count(EmergencyRequest.id)).group_by(EmergencyRequest.status).all()
    total_beds = sum(h.available_beds for h in Hospital.query.all())
    return render_template("admin_reports.html", category_counts=category_counts, status_counts=status_counts, total_beds=total_beds)


@app.route("/admin/simulation")
def admin_simulation():
    if not require_role("admin"):
        return redirect(url_for("admin_login"))
    return render_template("admin_simulation.html")


@app.route("/admin/simulate", methods=["POST"])
def admin_simulate():
    if not require_role("admin"):
        return redirect(url_for("admin_login"))
    scenario = request.form.get("scenario", "Flood")
    flash(f"SIMULATED DEMO DATA: {scenario} scenario prepared for demonstration.", "success")
    return redirect(url_for("admin_simulation"))


@app.route("/ambulance-register", methods=["GET", "POST"])
def ambulance_register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if AmbulanceProvider.query.filter_by(email=email).first():
            flash("An ambulance provider with that email already exists.", "error")
            return render_template("ambulance_register.html")
        provider = AmbulanceProvider(
            provider_name=request.form.get("provider_name"),
            contact_name=request.form.get("contact_name"),
            email=email,
            password_hash=generate_password_hash(request.form.get("password")),
            phone=request.form.get("phone"),
            registration_number=request.form.get("registration_number"),
            ambulance_type=request.form.get("ambulance_type"),
            service_area=request.form.get("service_area"),
            current_location=request.form.get("current_location"),
            latitude=float(request.form.get("latitude", 0.0) or 0.0),
            longitude=float(request.form.get("longitude", 0.0) or 0.0),
            verification_status="PENDING",
            availability_status="AVAILABLE",
        )
        db.session.add(provider)
        db.session.commit()
        flash("Ambulance registration submitted for verification.", "success")
        return redirect(url_for("ambulance_login"))
    return render_template("ambulance_register.html")


@app.route("/ambulance-login", methods=["GET", "POST"])
def ambulance_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        provider = AmbulanceProvider.query.filter_by(email=email).first()
        if provider and check_password_hash(provider.password_hash, request.form.get("password", "")):
            session["role"] = "ambulance"
            session["user_id"] = provider.id
            session["user_name"] = provider.provider_name
            return redirect(url_for("ambulance_dashboard"))
        flash("Invalid ambulance credentials.", "error")
    return render_template("ambulance_login.html")


@app.route("/ambulance/dashboard")
def ambulance_dashboard():
    if not require_role("ambulance"):
        return redirect(url_for("ambulance_login"))
    provider = AmbulanceProvider.query.get(session["user_id"])
    requests = EmergencyRequest.query.filter(
        func.lower(EmergencyRequest.required_assistance).like("%ambulance%")
    ).order_by(EmergencyRequest.created_at.desc()).all()
    return render_template("ambulance_dashboard.html", provider=provider, requests=requests)


@app.route("/api/ambulance/requests")
def api_ambulance_requests():
    if session.get("role") != "ambulance":
        return jsonify({"error": "Ambulance provider sign-in is required."}), 401

    requests = EmergencyRequest.query.filter(
        func.lower(EmergencyRequest.required_assistance).like("%ambulance%")
    ).order_by(EmergencyRequest.created_at.desc()).all()
    return jsonify([
        {
            "emergency_id": emergency.emergency_id,
            "name": emergency.name,
            "phone": emergency.phone,
            "category": emergency.category,
            "status": emergency.status,
            "priority": emergency.priority,
            "location": emergency.current_location,
            "required_assistance": emergency.required_assistance,
            "problem_description": emergency.problem_description,
            "latitude": emergency.latitude,
            "longitude": emergency.longitude,
            "created_at": emergency.created_at.isoformat() + "Z",
        }
        for emergency in requests
    ])


@app.route("/api/provider-location", methods=["POST"])
def update_provider_location():
    if session.get("role") != "ambulance":
        return jsonify({"error": "Ambulance provider sign-in is required."}), 401

    location = request.get_json()
    try:
        latitude = float(location.get("latitude"))
        longitude = float(location.get("longitude"))
    except (AttributeError, TypeError, ValueError):
        return jsonify({"error": "Valid latitude and longitude are required."}), 400

    if not (math.isfinite(latitude) and math.isfinite(longitude)
            and -90 <= latitude <= 90 and -180 <= longitude <= 180):
        return jsonify({"error": "Coordinates are outside the valid range."}), 400

    provider = db.session.get(AmbulanceProvider, session["user_id"])
    if not provider:
        session.clear()
        return jsonify({"error": "Ambulance provider account was not found."}), 401

    provider.latitude = latitude
    provider.longitude = longitude
    provider.current_location = "Live GPS location"
    db.session.commit()
    return jsonify({"status": "updated"})


@app.route("/ambulance-logout")
def ambulance_logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("ambulance_login"))


@app.route("/shelter-register", methods=["GET", "POST"])
def shelter_register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if ShelterProvider.query.filter_by(email=email).first():
            flash("A shelter account with that email already exists.", "error")
            return render_template("shelter_register.html")
        shelter = ShelterProvider(
            shelter_name=request.form.get("shelter_name"),
            contact_name=request.form.get("contact_name"),
            email=email,
            password_hash=generate_password_hash(request.form.get("password")),
            phone=request.form.get("phone"),
            address=request.form.get("address"),
            latitude=float(request.form.get("latitude", 0.0) or 0.0),
            longitude=float(request.form.get("longitude", 0.0) or 0.0),
            service_area=request.form.get("service_area"),
            total_capacity=int(request.form.get("total_capacity", 0) or 0),
            occupied_spaces=int(request.form.get("occupied_spaces", 0) or 0),
            available_spaces=int(request.form.get("available_spaces", 0) or 0),
            facilities=request.form.get("facilities", ""),
            verification_status="PENDING",
            availability_status="AVAILABLE",
        )
        db.session.add(shelter)
        db.session.commit()
        flash("Shelter registration submitted for verification.", "success")
        return redirect(url_for("shelter_login"))
    return render_template("shelter_register.html")


@app.route("/shelter-login", methods=["GET", "POST"])
def shelter_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        shelter = ShelterProvider.query.filter_by(email=email).first()
        if shelter and check_password_hash(shelter.password_hash, request.form.get("password", "")):
            session["role"] = "shelter"
            session["user_id"] = shelter.id
            session["user_name"] = shelter.shelter_name
            return redirect(url_for("shelter_dashboard"))
        flash("Invalid shelter credentials.", "error")
    return render_template("shelter_login.html")


@app.route("/shelter/dashboard")
def shelter_dashboard():
    if not require_role("shelter"):
        return redirect(url_for("shelter_login"))
    shelter = ShelterProvider.query.get(session["user_id"])
    return render_template("shelter_dashboard.html", shelter=shelter)


@app.route("/volunteer-register", methods=["GET", "POST"])
def volunteer_register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if Volunteer.query.filter_by(email=email).first():
            flash("This volunteer already exists.", "error")
            return render_template("volunteer_register.html")
        volunteer = Volunteer(
            name=request.form.get("name"),
            email=email,
            password_hash=generate_password_hash(request.form.get("password")),
            phone=request.form.get("phone"),
            skills=request.form.get("skills", ""),
            service_area=request.form.get("service_area", ""),
            availability="AVAILABLE",
            latitude=float(request.form.get("latitude", 0.0) or 0.0),
            longitude=float(request.form.get("longitude", 0.0) or 0.0),
            verification_status="PENDING",
        )
        db.session.add(volunteer)
        db.session.commit()
        flash("Volunteer profile created successfully.", "success")
        return redirect(url_for("volunteer_login"))
    return render_template("volunteer_register.html")


@app.route("/volunteer-login", methods=["GET", "POST"])
def volunteer_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        volunteer = Volunteer.query.filter_by(email=email).first()
        if volunteer and check_password_hash(volunteer.password_hash, request.form.get("password", "")):
            session["role"] = "volunteer"
            session["user_id"] = volunteer.id
            session["user_name"] = volunteer.name
            return redirect(url_for("volunteer_dashboard"))
        flash("Invalid volunteer credentials.", "error")
    return render_template("volunteer_login.html")


@app.route("/volunteer/dashboard")
def volunteer_dashboard():
    if not require_role("volunteer"):
        return redirect(url_for("volunteer_login"))
    volunteer = Volunteer.query.get(session["user_id"])
    return render_template("volunteer_dashboard.html", volunteer=volunteer)


@app.route("/hospital-directory")
def hospital_directory():
    hospitals = Hospital.query.all()
    return render_template("hospital_directory.html", hospitals=hospitals)


@app.route("/hospital-dashboard", methods=["GET", "POST"])
def hospital_dashboard():
    if not require_role("admin"):
        return redirect(url_for("admin_login"))
    if request.method == "POST":
        hospital_id = int(request.form.get("hospital_id"))
        hospital = Hospital.query.get(hospital_id)
        if hospital:
            hospital.total_beds = int(request.form.get("total_beds", hospital.total_beds) or hospital.total_beds)
            hospital.occupied_beds = int(request.form.get("occupied_beds", hospital.occupied_beds) or hospital.occupied_beds)
            hospital.available_beds = max(0, hospital.total_beds - hospital.occupied_beds)
            hospital.facilities = request.form.get("facilities", hospital.facilities)
            hospital.updated_at = utcnow_naive()
            db.session.commit()
            flash("Hospital capacity updated.", "success")
    hospitals = Hospital.query.all()
    return render_template("hospital_dashboard.html", hospitals=hospitals)


@app.route("/blood-donor-register", methods=["GET", "POST"])
def blood_donor_register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        blood_group = request.form.get("blood_group", "").strip()
        if blood_group not in BLOOD_GROUPS:
            flash("Please select a valid blood group.", "error")
            return render_template("blood_donor_register.html", blood_groups=BLOOD_GROUPS)
        if BloodDonor.query.filter_by(email=email).first():
            flash("Donor account already exists.", "error")
            return render_template("blood_donor_register.html", blood_groups=BLOOD_GROUPS)
        donor = BloodDonor(
            name=request.form.get("name"),
            email=email,
            password_hash=generate_password_hash(request.form.get("password")),
            phone=request.form.get("phone"),
            blood_group=blood_group,
            city=request.form.get("city", ""),
            preferred_location=request.form.get("preferred_location", ""),
            availability_status="AVAILABLE",
            consent=request.form.get("consent") == "on",
            verification_status="PENDING",
        )
        db.session.add(donor)
        db.session.commit()
        flash("Donor registration submitted.", "success")
        return redirect(url_for("blood_donor_login"))
    return render_template("blood_donor_register.html", blood_groups=BLOOD_GROUPS)


@app.route("/blood-donor-login", methods=["GET", "POST"])
def blood_donor_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        donor = BloodDonor.query.filter_by(email=email).first()
        if donor and check_password_hash(donor.password_hash, request.form.get("password", "")):
            session["role"] = "blood_donor"
            session["user_id"] = donor.id
            session["user_name"] = donor.name
            return redirect(url_for("blood_donor_dashboard"))
        flash("Invalid donor credentials.", "error")
    return render_template("blood_donor_login.html")


@app.route("/blood-donor/dashboard")
def blood_donor_dashboard():
    if not require_role("blood_donor"):
        return redirect(url_for("blood_donor_login"))
    donor = BloodDonor.query.get(session["user_id"])
    return render_template("blood_donor_dashboard.html", donor=donor)


@app.route("/blood-request", methods=["GET", "POST"])
def blood_request():
    if request.method == "POST":
        blood_group = request.form.get("blood_group", "").strip()
        if blood_group not in BLOOD_GROUPS:
            flash("Please select a valid blood group.", "error")
            return render_template("blood_request.html", blood_groups=BLOOD_GROUPS)
        request_data = BloodRequest(
            patient_name=request.form.get("patient_name"),
            blood_group=blood_group,
            location=request.form.get("location"),
            urgency=request.form.get("urgency", "High"),
            status="PENDING",
        )
        db.session.add(request_data)
        db.session.commit()
        flash("Blood request submitted to the donor network.", "success")
        return redirect(url_for("blood_request"))
    return render_template("blood_request.html", blood_groups=BLOOD_GROUPS)


@app.route("/notifications")
def notifications():
    items = Notification.query.order_by(Notification.created_at.desc()).all()
    return render_template("notifications.html", notifications=items)


@app.route("/user-profile")
def user_profile():
    return render_template("user_profile.html")


@app.route("/api/summary")
def api_summary():
    return jsonify({
        "total_requests": EmergencyRequest.query.count(),
        "pending": EmergencyRequest.query.filter_by(status="PENDING").count(),
        "ambulances_available": AmbulanceProvider.query.filter_by(availability_status="AVAILABLE").count(),
        "shelters_available": ShelterProvider.query.filter_by(availability_status="AVAILABLE").count(),
        "beds_available": sum(h.available_beds for h in Hospital.query.all()),
    })


@app.route("/api/requests")
def api_requests():
    payload = []
    for r in EmergencyRequest.query.order_by(EmergencyRequest.created_at.desc()).all():
        payload.append({
            "id": r.id,
            "emergency_id": r.emergency_id,
            "name": r.name,
            "category": r.category,
            "status": r.status,
            "priority": r.priority,
            "latitude": r.latitude,
            "longitude": r.longitude,
            "location": r.current_location,
            "created_at": r.created_at.isoformat(),
        })
    return jsonify(payload)


@app.route("/api/admin/live-locations")
def api_admin_live_locations():
    if session.get("role") != "admin":
        return jsonify({"error": "Administrator sign-in is required."}), 401

    emergency_requests = EmergencyRequest.query.order_by(EmergencyRequest.created_at.desc()).all()
    ambulances = AmbulanceProvider.query.all()

    def valid_coordinates(latitude, longitude):
        return (
            latitude is not None and longitude is not None
            and math.isfinite(latitude) and math.isfinite(longitude)
            and -90 <= latitude <= 90 and -180 <= longitude <= 180
            and (latitude != 0 or longitude != 0)
        )

    return jsonify({
        "requests": [
            {
                "id": emergency.emergency_id,
                "name": emergency.name,
                "category": emergency.category,
                "status": emergency.status,
                "priority": emergency.priority,
                "location": emergency.current_location,
                "required_assistance": emergency.required_assistance,
                "latitude": emergency.latitude,
                "longitude": emergency.longitude,
            }
            for emergency in emergency_requests
            if valid_coordinates(emergency.latitude, emergency.longitude)
        ],
        "ambulances": [
            {
                "id": provider.id,
                "name": provider.provider_name,
                "type": provider.ambulance_type,
                "availability": provider.availability_status,
                "location": provider.current_location,
                "latitude": provider.latitude,
                "longitude": provider.longitude,
            }
            for provider in ambulances
            if valid_coordinates(provider.latitude, provider.longitude)
        ],
        "updated_at": utcnow_naive().isoformat() + "Z",
    })


@app.route("/api/hospitals")
def api_hospitals():
    payload = []
    for h in Hospital.query.all():
        payload.append({
            "id": h.id,
            "name": h.name,
            "latitude": h.latitude,
            "longitude": h.longitude,
            "available_beds": h.available_beds,
            "address": h.address,
        })
    return jsonify(payload)


@app.route("/api/reverse-geocode")
def reverse_geocode():
    try:
        latitude = float(request.args.get("lat", ""))
        longitude = float(request.args.get("lon", ""))
    except (TypeError, ValueError):
        return jsonify({"error": "Valid latitude and longitude are required."}), 400

    if not (math.isfinite(latitude) and math.isfinite(longitude)
            and -90 <= latitude <= 90 and -180 <= longitude <= 180):
        return jsonify({"error": "Coordinates are outside the valid range."}), 400

    query = urlencode({
        "format": "jsonv2",
        "lat": latitude,
        "lon": longitude,
        "zoom": 18,
        "addressdetails": 1,
    })
    try:
        result = jsonify(nominatim_json(f"https://nominatim.openstreetmap.org/reverse?{query}", timeout=8))
        result.headers["Cache-Control"] = "public, max-age=60"
        return result
    except HTTPError as error:
        app.logger.warning("Reverse geocoding provider returned HTTP %s", error.code)
    except (URLError, TimeoutError, OSError, ValueError) as error:
        app.logger.warning("Reverse geocoding request failed: %s", error)

    return jsonify({"error": "Address lookup is temporarily unavailable."}), 502


@app.route("/api/nearby-hospitals")
def nearby_hospitals():
    try:
        latitude = float(request.args.get("lat", ""))
        longitude = float(request.args.get("lon", ""))
    except (TypeError, ValueError):
        return jsonify({"error": "Valid latitude and longitude are required."}), 400

    if not (math.isfinite(latitude) and math.isfinite(longitude)
            and -90 <= latitude <= 90 and -180 <= longitude <= 180):
        return jsonify({"error": "Coordinates are outside the valid range."}), 400

    cache_key = (round(latitude, 3), round(longitude, 3))
    cached = NEARBY_HOSPITALS_CACHE.get(cache_key)
    if cached and (utcnow_naive() - cached["created_at"]).total_seconds() < 300:
        return jsonify(cached["data"])

    radius_meters = 10000
    latitude_span = radius_meters / 111320
    longitude_span = min(180, latitude_span / max(math.cos(math.radians(latitude)), 0.01))
    query = urlencode({
        "amenity": "hospital",
        "format": "jsonv2",
        "limit": 50,
        "addressdetails": 1,
        "viewbox": (
            f"{max(-180, longitude - longitude_span)},"
            f"{min(90, latitude + latitude_span)},"
            f"{min(180, longitude + longitude_span)},"
            f"{max(-90, latitude - latitude_span)}"
        ),
        "bounded": 1,
    })
    try:
        elements = nominatim_json(f"https://nominatim.openstreetmap.org/search?{query}")
    except HTTPError as error:
        app.logger.warning("Nearby hospitals provider returned HTTP %s", error.code)
        return jsonify({"error": "Nearby hospital data is temporarily unavailable."}), 502
    except (URLError, TimeoutError, OSError, ValueError) as error:
        app.logger.warning("Nearby hospitals lookup failed: %s", error)
        return jsonify({"error": "Nearby hospital data is temporarily unavailable."}), 502

    hospitals = []
    seen = set()
    for element in elements:
        hospital_latitude = element.get("lat")
        hospital_longitude = element.get("lon")
        if (hospital_latitude is None or hospital_longitude is None
                or element.get("type") != "hospital"):
            continue

        hospital_latitude = float(hospital_latitude)
        hospital_longitude = float(hospital_longitude)
        name = element.get("name")
        if not name:
            continue

        lat_delta = math.radians(hospital_latitude - latitude)
        lon_delta = math.radians(hospital_longitude - longitude)
        haversine = (
            math.sin(lat_delta / 2) ** 2
            + math.cos(math.radians(latitude))
            * math.cos(math.radians(hospital_latitude))
            * math.sin(lon_delta / 2) ** 2
        )
        distance_km = 6371 * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))
        if distance_km > radius_meters / 1000:
            continue

        osm_key = (element.get("osm_type"), element.get("osm_id"))
        if osm_key in seen:
            continue
        seen.add(osm_key)

        address_details = element.get("address") or {}
        locality = next(
            (
                address_details[key]
                for key in ("neighbourhood", "suburb", "village", "town", "city", "municipality")
                if address_details.get(key)
            ),
            "",
        )
        district = address_details.get("state_district") or address_details.get("county", "")
        address = ", ".join(dict.fromkeys(part for part in (locality, district) if part))

        hospitals.append({
            "name": name,
            "latitude": hospital_latitude,
            "longitude": hospital_longitude,
            "distance_km": distance_km,
            "address": address,
            "osm_type": element.get("osm_type", ""),
            "osm_id": element.get("osm_id"),
        })

    hospitals.sort(key=lambda hospital: hospital["distance_km"])
    hospitals = hospitals[:1]
    for hospital in hospitals:
        hospital["distance_km"] = round(hospital["distance_km"], 1)
    payload = {
        "hospitals": hospitals,
        "radius_km": radius_meters // 1000,
        "source": "OpenStreetMap",
    }
    NEARBY_HOSPITALS_CACHE[cache_key] = {
        "created_at": utcnow_naive(),
        "data": payload,
    }
    return jsonify(payload)


@app.errorhandler(404)
def not_found(_):
    return render_template("404.html"), 404


@app.route("/favicon.ico")
def favicon():
    return redirect(url_for("static", filename="favicon.svg"))


def require_role(role):
    if session.get("role") != role:
        flash("You do not have permission to access that page.", "error")
        return False
    return True


@app.cli.command("init-db")
def init_db_command():
    """Create missing tables in the configured database without migrating data."""
    db.create_all()
    if db.engine.dialect.name == "postgresql":
        emergency_id_column = next(
            column for column in inspect(db.engine).get_columns("emergency_request")
            if column["name"] == "emergency_id"
        )
        emergency_id_length = getattr(emergency_id_column["type"], "length", None)
        if emergency_id_length is not None and emergency_id_length < 40:
            with db.engine.begin() as connection:
                connection.exec_driver_sql(
                    "ALTER TABLE emergency_request ALTER COLUMN emergency_id TYPE VARCHAR(40)"
                )
    click.echo("Database schema initialized. Existing records were not copied or reset.")


@app.cli.command("create-admin")
@click.option("--email", prompt=True)
@click.option("--name", prompt="Admin name")
@click.password_option(confirmation_prompt=True)
def create_admin_command(email, name, password):
    """Create an administrator account using an interactive password prompt."""
    email = email.strip().lower()
    name = name.strip()
    if not email or not name or not password:
        raise click.ClickException("Email, name, and password must not be empty.")
    if Admin.query.filter_by(email=email).first():
        raise click.ClickException("An administrator with that email already exists.")

    db.session.add(Admin(
        name=name,
        email=email,
        password_hash=generate_password_hash(password),
    ))
    try:
        db.session.commit()
    except SQLAlchemyError as error:
        db.session.rollback()
        app.logger.error("Failed to create administrator (database error: %s).", type(error).__name__)
        raise click.ClickException("Could not create the administrator account.") from None
    click.echo("Administrator account created.")


if not is_vercel and parsed_database_url.get_backend_name() == "sqlite":
    with app.app_context():
        db.create_all()
        create_seed_data()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
