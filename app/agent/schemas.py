from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field


class LogExpense(BaseModel):
    """Money the user spent."""
    kind: Literal["log_expense"] = "log_expense"
    amount: float = Field(description="Amount in taka, e.g. 350")
    category: str | None = Field(
        default=None,
        description="One of: Food, Transport, Groceries, Bills, Health, "
                    "Shopping, Education, Other",
    )
    pay_method: Literal["cash", "bkash", "nagad", "card", "bank"] | None = None
    note: str | None = None
    date: str | None = Field(default=None, description="ISO date, e.g. 2026-10-08")
    confidence: float = 0.9


class AddReminder(BaseModel):
    """Something to be reminded about at a time."""
    kind: Literal["add_reminder"] = "add_reminder"
    title: str
    when_local: str | None = Field(
        default=None,
        description="Local wall clock, 'YYYY-MM-DDTHH:MM'. Null if no time was given.",
    )
    rrule: str | None = Field(
        default=None, description="e.g. FREQ=DAILY or FREQ=MONTHLY;BYMONTHDAY=10"
    )
    confidence: float = 0.9


class SaveMemory(BaseModel):
    """A fact, number, or statement worth remembering."""
    kind: Literal["save_memory"] = "save_memory"
    content: str = Field(description="The user's own wording, cleaned up")
    subject: str | None = Field(default=None, description="e.g. internet, Tanvir")
    canonical: str = Field(description="Short ENGLISH keyword line for searching")
    confidence: float = 0.9


class ListAdd(BaseModel):
    kind: Literal["list_add"] = "list_add"
    list_name: str = "Bazar"
    items: list[str]
    confidence: float = 0.9


class ListTick(BaseModel):
    kind: Literal["list_tick"] = "list_tick"
    list_name: str | None = None
    items: list[str]
    confidence: float = 0.9


class Query(BaseModel):
    """A question about data already saved. Never answered by the model itself."""
    kind: Literal["query"] = "query"
    topic: Literal[
        "expense_report", "memory_recall", "list_show", "reminders_pending"
    ]
    canonical: str = Field(description="The question rewritten as English keywords")
    period: Literal["today", "this_week", "this_month", "last_month"] | None = None
    category: str | None = None
    list_name: str | None = None
    confidence: float = 0.9


class Undo(BaseModel):
    kind: Literal["undo"] = "undo"
    confidence: float = 1.0


class Unknown(BaseModel):
    """Could not classify. The runtime saves the raw text as a note."""
    kind: Literal["unknown"] = "unknown"
    confidence: float = 0.0


Action = Annotated[
    Union[LogExpense, AddReminder, SaveMemory, ListAdd, ListTick, Query, Undo, Unknown],
    Field(discriminator="kind"),
]


class ParseResult(BaseModel):
    lang: Literal["bn", "banglish", "en"] = "banglish"
    actions: list[Action] = Field(default_factory=list)
