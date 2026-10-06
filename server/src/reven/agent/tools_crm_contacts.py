"""CRM contacts MCP adapter: input conversion and Chinese output."""

from typing import Annotated

from pydantic import Field

from reven.agent.crm_tool_support import (
    ConfirmCustomerNameParam,
    ContactIdParam,
    CustomerIdParam,
    _collect_updates,
    _confirm_customer_name,
    _customer_not_found,
    _mutation_errors,
    _validate,
)
from reven.agent.tool_binding import ToolSessionBinding
from reven.crm.inputs import ContactCreate, ContactUpdate
from reven.crm.models import Contact
from reven.crm.repository import CrmRepository
from reven.crm.service import CrmService


class CrmContactTools(ToolSessionBinding):
    async def list_contacts(self, customer_id: CustomerIdParam) -> str:
        """列出指定客户的全部联系人（主联系人排在最前）。"""
        async with self._session() as session:
            repository = CrmRepository(session)
            customer = await repository.get_customer(customer_id)
            if customer is None:
                raise _customer_not_found(customer_id)
            contacts = await repository.list_contacts(customer_id)
        if not contacts:
            return f"客户「{customer.name}」暂无联系人，可用 crm_contact_create 添加。"
        header = f"客户「{customer.name}」的联系人（{len(contacts)}）："
        lines = [_contact_line(index, contact) for index, contact in enumerate(contacts, 1)]
        return "\n".join([header, *lines])

    async def create_contact(
        self,
        customer_id: CustomerIdParam,
        name: Annotated[str, Field(description="联系人姓名（必填）")],
        role: Annotated[str | None, Field(description="职务，如：创始人、HR 总监")] = None,
        phone: Annotated[str | None, Field(description="电话")] = None,
        email: Annotated[str | None, Field(description="邮箱")] = None,
        wechat: Annotated[str | None, Field(description="微信号")] = None,
        is_primary: Annotated[bool, Field(description="是否设为主联系人（每个客户最多一个）")] = False,
        notes: Annotated[str | None, Field(description="备注")] = None,
    ) -> str:
        """为客户新增联系人。设为主联系人时，原主联系人会自动降级为普通联系人。"""
        payload = _validate(
            ContactCreate,
            {
                "name": name,
                "role": role,
                "phone": phone,
                "email": email,
                "wechat": wechat,
                "is_primary": is_primary,
                "notes": notes,
            },
        )
        with _mutation_errors():
            async with self._session() as session:
                customer, contact = await CrmService(session, commit=self._commits).create_contact(customer_id, payload)
                self._record_entity(contact)
        suffix = "，已设为该客户唯一主联系人" if contact.is_primary else ""
        return f"已为客户「{customer.name}」新增联系人「{contact.name}」（id={contact.id}）{suffix}。"

    async def update_contact(
        self,
        customer_id: CustomerIdParam,
        contact_id: ContactIdParam,
        name: Annotated[str | None, Field(description="新姓名；不传则不修改")] = None,
        role: Annotated[str | None, Field(description="新职务；传空字符串表示清空")] = None,
        phone: Annotated[str | None, Field(description="新电话；传空字符串表示清空")] = None,
        email: Annotated[str | None, Field(description="新邮箱；传空字符串表示清空")] = None,
        wechat: Annotated[str | None, Field(description="新微信号；传空字符串表示清空")] = None,
        is_primary: Annotated[bool | None, Field(description="true=设为主联系人，false=取消主联系人")] = None,
        notes: Annotated[str | None, Field(description="新备注；传空字符串表示清空")] = None,
    ) -> str:
        """修改联系人信息（部分更新，只传要改的字段）。设为主联系人时自动顶替原主联系人。"""
        values = _collect_updates(
            {
                "name": name,
                "role": role,
                "phone": phone,
                "email": email,
                "wechat": wechat,
                "is_primary": is_primary,
                "notes": notes,
            }
        )
        payload = _validate(ContactUpdate, values)
        with _mutation_errors():
            async with self._session() as session:
                updated = await CrmService(session, commit=self._commits).update_contact(
                    customer_id, contact_id, payload
                )
                self._record_entity(updated)
        return f"已更新联系人：{_contact_line(0, updated).removeprefix('0. ')}"

    async def delete_contact(
        self, customer_id: CustomerIdParam, contact_id: ContactIdParam, confirm_customer_name: ConfirmCustomerNameParam
    ) -> str:
        """删除一个联系人；相关跟进记录会保留，其中的联系人信息以姓名快照形式留存。

        调用前必须与用户确认删除意图，并把所属客户名称逐字填入 confirm_customer_name。
        """
        with _mutation_errors():
            async with self._session() as session:
                await _confirm_customer_name(session, customer_id, confirm_customer_name)
                contact = await CrmService(session, commit=self._commits).delete_contact(customer_id, contact_id)
                self._record_entity(contact)
                name = contact.name
        return f"已删除联系人「{name}」（id={contact_id}）；相关跟进记录已保留，联系人信息以快照留存。"


def _contact_line(index: int, contact: Contact) -> str:
    primary = "，主联系人" if contact.is_primary else ""
    parts = [f"{index}. {contact.name}（id={contact.id}{primary}）"]
    if contact.role:
        parts.append(contact.role)
    if contact.phone:
        parts.append(f"电话：{contact.phone}")
    if contact.email:
        parts.append(f"邮箱：{contact.email}")
    if contact.wechat:
        parts.append(f"微信：{contact.wechat}")
    if contact.notes:
        parts.append(f"备注：{contact.notes}")
    return "｜".join(parts)
