from fastapi import FastAPI, APIRouter, Depends, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import os
import logging
from pathlib import Path
from dotenv import load_dotenv
import uuid
from pydantic import BaseModel, Field, EmailStr
from enum import Enum
import openpyxl
from pathlib import Path


# Load environment variables
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
MONGO_URL = os.getenv('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.getenv('DB_NAME', 'surveyapp')

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

# Embedded models for simplicity
class SurveySubmission(BaseModel):
    # Personal Information
    firstName: str
    lastName: str
    email: EmailStr
    phoneNumber: str
    age: str
    
    # Professional Information
    jobTitle: str
    company: str
    industry: str
    workExperience: str
    
    # Preferences and Ratings
    communicationPreference: str
    satisfactionRating: int = Field(ge=1, le=5)
    recommendationLikelihood: int = Field(ge=1, le=5)
    productUsageFrequency: str
    
    # Additional Information
    feedback: Optional[str] = ""
    improvements: Optional[str] = ""


class SurveyResponse(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    # Personal Information
    first_name: str
    last_name: str
    email: EmailStr
    phone_number: str
    age: str
    
    # Professional Information
    job_title: str
    company: str
    industry: str
    work_experience: str
    
    # Preferences and Ratings
    communication_preference: str
    satisfaction_rating: int = Field(ge=1, le=5)
    recommendation_likelihood: int = Field(ge=1, le=5)
    product_usage_frequency: str
    
    # Additional Information
    feedback: Optional[str] = ""
    improvements: Optional[str] = ""
    
    # Metadata
    submitted_at: datetime = Field(default_factory=datetime.utcnow)
    user_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

# Create FastAPI app
app = FastAPI(
    title="SurveyPro API",
    description="Professional Survey Application Backend",
    version="1.0.0"
)

# Create API router
api_router = APIRouter(prefix="/api")
security = HTTPBearer()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Dependency to get database
async def get_database() -> AsyncIOMotorDatabase:
    return db


# Health check endpoint
@api_router.get("/")
async def root():
    return {"message": "Hello World", "status": "healthy", "timestamp": datetime.utcnow()}


# Survey endpoints
@api_router.post("/survey", response_model=Dict[str, Any])
async def submit_survey(
    survey: SurveySubmission,
    request: Request,
    database: AsyncIOMotorDatabase = Depends(get_database)
):
    """Submit a new survey response."""
    try:
        logger.info(f"Received survey submission: {survey.firstName} {survey.lastName}")
        
        # Convert frontend field names to backend field names
        survey_response = SurveyResponse(
            first_name=survey.firstName,
            last_name=survey.lastName,
            email=survey.email,
            phone_number=survey.phoneNumber,
            age=survey.age,
            job_title=survey.jobTitle,
            company=survey.company,
            industry=survey.industry,
            work_experience=survey.workExperience,
            communication_preference=survey.communicationPreference,
            satisfaction_rating=survey.satisfactionRating,
            recommendation_likelihood=survey.recommendationLikelihood,
            product_usage_frequency=survey.productUsageFrequency,
            feedback=survey.feedback or "",
            improvements=survey.improvements or "",
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent")
        )
        
        # Insert into database
        result = await database.survey_responses.insert_one(survey_response.dict())
        save_to_excel(survey_response)

        logger.info(f"Survey submitted successfully: {result.inserted_id}")
        
        return {
            "success": True,
            "message": "Survey submitted successfully",
            "survey_id": survey_response.id,
            "submitted_at": survey_response.submitted_at
        }
    except Exception as e:
        logger.error(f"Error submitting survey: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit survey. Please try again."
        )


@api_router.get("/surveys", response_model=List[SurveyResponse])
async def get_surveys(
    skip: int = 0,
    limit: int = 100,
    database: AsyncIOMotorDatabase = Depends(get_database)
):
    """Get all survey responses."""
    try:
        cursor = database.survey_responses.find().skip(skip).limit(limit).sort("submitted_at", -1)
        surveys = await cursor.to_list(length=limit)
        return [SurveyResponse(**survey) for survey in surveys]
    except Exception as e:
        logger.error(f"Error fetching surveys: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch surveys"
        )


@api_router.get("/surveys/stats")
async def get_survey_stats(
    database: AsyncIOMotorDatabase = Depends(get_database)
):
    """Get survey statistics."""
    try:
        # Get total count
        total_responses = await database.survey_responses.count_documents({})
        
        # Get all surveys for calculations
        surveys = await database.survey_responses.find().to_list(length=None)
        
        if not surveys:
            return {
                "total_responses": 0,
                "average_satisfaction": 0,
                "average_recommendation": 0,
                "industry_breakdown": {},
                "communication_preferences": {},
                "usage_frequency": {},
                "recent_responses": []
            }
        
        # Calculate averages
        avg_satisfaction = sum(s["satisfaction_rating"] for s in surveys) / len(surveys)
        avg_recommendation = sum(s["recommendation_likelihood"] for s in surveys) / len(surveys)
        
        # Industry breakdown
        industry_breakdown = {}
        for survey in surveys:
            industry = survey["industry"]
            industry_breakdown[industry] = industry_breakdown.get(industry, 0) + 1
        
        # Communication preferences
        comm_prefs = {}
        for survey in surveys:
            pref = survey["communication_preference"]
            comm_prefs[pref] = comm_prefs.get(pref, 0) + 1
        
        # Usage frequency
        usage_freq = {}
        for survey in surveys:
            freq = survey["product_usage_frequency"]
            usage_freq[freq] = usage_freq.get(freq, 0) + 1
        
        # Recent responses (last 10)
        recent_surveys = sorted(surveys, key=lambda x: x["submitted_at"], reverse=True)[:10]
        recent_responses = [
            {
                "id": s["id"],
                "name": f"{s['first_name']} {s['last_name']}",
                "email": s["email"],
                "company": s["company"],
                "submitted_at": s["submitted_at"],
                "satisfaction_rating": s["satisfaction_rating"]
            }
            for s in recent_surveys
        ]
        
        return {
            "total_responses": total_responses,
            "average_satisfaction": round(avg_satisfaction, 2),
            "average_recommendation": round(avg_recommendation, 2),
            "industry_breakdown": industry_breakdown,
            "communication_preferences": comm_prefs,
            "usage_frequency": usage_freq,
            "recent_responses": recent_responses
        }
    except Exception as e:
        logger.error(f"Error fetching survey stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch survey statistics"
        )


# Include the router in the main app
app.include_router(api_router)


# Startup event to create indexes
@app.on_event("startup")
async def startup_event():
    """Create database indexes on startup."""
    try:
        # Create indexes for better performance
        await db.survey_responses.create_index("submitted_at")
        await db.survey_responses.create_index("email")
        logger.info("Database indexes created successfully")
    except Exception as e:
        logger.error(f"Error creating database indexes: {e}")


# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    """Close database connection on shutdown."""
    client.close()
    logger.info("Database connection closed")


def save_to_excel(survey):
    excel_file = Path("survey_responses.xlsx")

    # If the Excel file does not exist, create it and add headers
    if not excel_file.exists():
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append([
            "First Name", "Last Name", "Email", "Phone Number", "Age",
            "Job Title", "Company", "Industry", "Work Experience",
            "Communication Preference", "Satisfaction Rating", "Recommendation Likelihood",
            "Product Usage Frequency", "Feedback", "Improvements", "Submitted At"
        ])
        workbook.save(excel_file)

    # Open the existing Excel file
    workbook = openpyxl.load_workbook(excel_file)
    sheet = workbook.active

    # Append the new survey response
    sheet.append([
        survey.first_name, survey.last_name, survey.email, survey.phone_number, survey.age,
        survey.job_title, survey.company, survey.industry, survey.work_experience,
        survey.communication_preference, survey.satisfaction_rating, survey.recommendation_likelihood,
        survey.product_usage_frequency, survey.feedback, survey.improvements, survey.submitted_at.isoformat()
    ])

    workbook.save(excel_file)
