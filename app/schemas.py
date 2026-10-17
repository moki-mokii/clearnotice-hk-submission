from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, field_validator, model_validator

from .source import normalize

Nonblank = Annotated[str, StringConstraints(min_length=1, pattern=r'\S')]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class AnalyzeRequest(StrictModel):
    text: str
    output_language: Literal['zh-Hant', 'en'] = 'zh-Hant'
    source_label: str = Field(default='', max_length=120)
    source_url: str = Field(default='', max_length=2048)
    input_kind: Literal['pasted'] = 'pasted'

    @field_validator('text')
    @classmethod
    def valid_text(cls, text):
        text = normalize(text)
        if not 30 <= len(text) <= 12000:
            raise ValueError('Normalized notice must contain 30 to 12000 Unicode code points')
        return text

    @field_validator('source_url')
    @classmethod
    def valid_url(cls, url):
        if url:
            HttpUrl(url)  # http/https only; never fetched
        return url


class ImportRequest(StrictModel):
    url: str = Field(min_length=1, max_length=2048)


class Evidence(StrictModel):
    line_id: str = Field(pattern=r'^L\d{4,5}$')
    quote: Nonblank = Field(max_length=500)


class Fact(StrictModel):
    status: Literal['stated', 'missing', 'uncertain']
    value: Nonblank | None = Field(max_length=1500)
    evidence: list[Evidence] = Field(max_length=16)

    @model_validator(mode='after')
    def consistency(self):
        if self.status == 'stated' and (self.value is None or not self.evidence):
            raise ValueError('stated requires value and evidence')
        if self.status in ('missing', 'uncertain') and self.value is not None:
            raise ValueError('missing/uncertain require null value')
        if self.status == 'missing' and self.evidence:
            raise ValueError('missing requires empty evidence')
        return self


class Facts(StrictModel):
    subject: Fact
    audience: Fact
    event_time: Fact
    registration_deadline: Fact
    location: Fact
    fee: Fact
    method: Fact
    conditions: Fact


class Item(StrictModel):
    text: Nonblank = Field(max_length=600)
    evidence: list[Evidence] = Field(min_length=1, max_length=16)


class CompactFact(Fact):
    value: Nonblank | None = Field(max_length=450)


class CompactTitle(CompactFact):
    value: Nonblank | None = Field(max_length=80)


class CompactFacts(StrictModel):
    subject: CompactTitle
    audience: CompactFact
    event_time: CompactFact
    registration_deadline: CompactFact
    location: CompactFact
    fee: CompactFact
    method: CompactFact
    conditions: CompactFact


class CompactItem(Item):
    text: Nonblank = Field(max_length=240)


class CardPreview(StrictModel):
    overview: CompactItem
    facts: CompactFacts
    next_step: CompactItem | None


class Result(StrictModel):
    facts: Facts
    summary: list[Item] = Field(min_length=1, max_length=3)
    actions: list[Item] = Field(max_length=6)
    card: CardPreview | None = None
