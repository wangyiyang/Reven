"""品牌与发布设置的对外 schema。"""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


class BrandColors(BaseModel):
    primary: HexColor = "#00E676"
    text: HexColor = "#0A0A0A"
    background: HexColor = "#FAFAFA"


class BrandFonts(BaseModel):
    body: ShortText = ""
    mono: ShortText = ""


class BrandProfilePayload(BaseModel):
    brand_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    intro: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""
    default_author: Annotated[str, StringConstraints(strip_whitespace=True, max_length=16)] = ""
    handle: Annotated[str, StringConstraints(strip_whitespace=True, max_length=64)] = ""
    website: ShortText = ""
    tagline: ShortText = ""
    colors: BrandColors = BrandColors()
    fonts: BrandFonts = BrandFonts()
    style_notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""


class WeChatTheme(BaseModel):
    primary_color: HexColor = "#00E676"
    font_family: ShortText = ""
    font_size: int = Field(default=16, ge=12, le=24)


class FooterModule(BaseModel):
    key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    type: Literal["text", "image"]
    content: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""
    asset_id: UUID | None = None
    enabled: bool = True


class WeChatTemplatePayload(BaseModel):
    theme: WeChatTheme = WeChatTheme()
    footer_modules: list[FooterModule] = []


class BlogTemplatePayload(BaseModel):
    author: Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)] = ""
    cover_fallback_asset_id: UUID | None = None
    og_image_asset_id: UUID | None = None


TemplatePayload = WeChatTemplatePayload | BlogTemplatePayload


class BrandVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version: int
    status: str
    payload: dict[str, object]
    source: str
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BrandProfileResponse(BaseModel):
    published: BrandVersionResponse | None
    draft: BrandVersionResponse | None


class TemplateVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel: str
    version: int
    status: str
    payload: dict[str, object]
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ChannelTemplateResponse(BaseModel):
    published: TemplateVersionResponse | None
    draft: TemplateVersionResponse | None


class BrandAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    purpose: str
    label: str
    enabled: bool
    public_url: str
    sha256: str
    mime_type: str
    byte_size: int
    width: int | None
    height: int | None
    source: str
    created_at: datetime


class BrandAssetCreatedResponse(BaseModel):
    asset: BrandAssetResponse
    created: bool


class BrandAssetUpdate(BaseModel):
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)] | None = None
    enabled: bool | None = None
