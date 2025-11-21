"""
Database Schemas for Company Operations App

Each Pydantic model represents a MongoDB collection.
Collection name is the lowercase of the class name.
"""
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, Literal
from datetime import date

class User(BaseModel):
    """
    Users collection schema
    Collection name: "user"
    """
    name: str = Field(..., description="Full name")
    email: EmailStr = Field(..., description="Email address")
    role: Literal["employee", "core"] = Field("employee", description="Role in the company")
    password_hash: str = Field(..., description="Hashed password (store hash, not plain text)")
    is_active: bool = Field(True, description="Whether user is active")

class Task(BaseModel):
    """
    Tasks assigned for follow-ups and work tracking
    Collection name: "task"
    """
    title: str = Field(..., description="Task title")
    description: Optional[str] = Field(None, description="Task details")
    assignee_email: EmailStr = Field(..., description="Employee email to whom the task is assigned")
    status: Literal["pending", "in_progress", "done"] = Field("pending")
    due_date: Optional[date] = Field(None)

class Report(BaseModel):
    """
    Daily reports submitted by employees
    Collection name: "report"
    """
    employee_email: EmailStr = Field(...)
    report_date: date = Field(..., description="Report date")
    summary: str = Field(..., description="What was done")
    hours_worked: float = Field(..., ge=0, le=24)

class SalaryPayment(BaseModel):
    """
    Salary updates and payments
    Collection name: "salarypayment"
    """
    employee_email: EmailStr = Field(...)
    amount: float = Field(..., ge=0)
    month: str = Field(..., description="e.g., 2025-01")
    notes: Optional[str] = None
    status: Literal["pending", "paid"] = Field("paid")

class FinanceRecord(BaseModel):
    """
    Revenue and spending records (core team only)
    Collection name: "financerecord"
    """
    kind: Literal["revenue", "expense"] = Field(...)
    amount: float = Field(..., ge=0)
    category: str = Field(..., description="Category like Sales, Marketing, Ops")
    description: Optional[str] = None
    reference: Optional[str] = Field(None, description="Invoice/PO/Txn ref")
