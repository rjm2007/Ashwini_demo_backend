export enum UserRole {
  ADMIN = "admin",
  REVIEWER = "reviewer",
  USER = "user"
}

const roleOrder: Record<UserRole, number> = {
  [UserRole.ADMIN]: 3,
  [UserRole.REVIEWER]: 2,
  [UserRole.USER]: 1
};

export function hasRoleOrHigher(userRole: UserRole, requiredRole: UserRole): boolean {
  // This function checks role hierarchy where admin is highest.
  return roleOrder[userRole] >= roleOrder[requiredRole];
}
