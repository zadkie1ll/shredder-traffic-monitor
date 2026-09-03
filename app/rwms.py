from __future__ import annotations

import logging

from common.rwms_client import RwmsClient as CommonRwmsClient

import proto.rwmanager_pb2 as proto


class RwmsClient(CommonRwmsClient):
    async def disable_user(self, user) -> bool:
        try:
            response = await self.update_user(
                proto.UpdateUserRequest(
                    user_id=user.id,
                    status=proto.UserStatus.DISABLED,
                    active_internal_squads=[
                        squad.uuid for squad in user.active_internal_squads
                    ],
                )
            )
        except (TypeError, ValueError) as exc:
            logging.getLogger(self.__class__.__name__).error(
                "error disabling user username=%s uuid=%s: %s",
                getattr(user, "username", None),
                getattr(user, "id", None) or getattr(user, "uuid", None),
                exc,
            )
            return False

        return response is not None
