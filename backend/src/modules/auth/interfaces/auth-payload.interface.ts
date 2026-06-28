import { UserRole } from "../../../common/enums/user-role.enum";

export interface AuthPayload {
  userId: string;
  email: string;
  role: UserRole;
}
