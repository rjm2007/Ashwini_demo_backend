import { CanActivate, ExecutionContext, ForbiddenException, Injectable } from "@nestjs/common";
import { Reflector } from "@nestjs/core";
import { ROLES_KEY } from "../decorators/roles.decorator";
import { hasRoleOrHigher, UserRole } from "../enums/user-role.enum";

@Injectable()
export class RolesGuard implements CanActivate {
  constructor(private readonly reflector: Reflector) {}

  canActivate(context: ExecutionContext): boolean {
    // This function validates the authenticated user has the required role.
    const requiredRoles = this.reflector.getAllAndOverride<UserRole[]>(ROLES_KEY, [
      context.getHandler(),
      context.getClass()
    ]);
    if (!requiredRoles || requiredRoles.length === 0) {
      return true;
    }

    const request = context.switchToHttp().getRequest();
    const user = request.user as { role?: UserRole } | undefined;
    if (!user?.role) {
      throw new ForbiddenException("Missing role context");
    }

    const allowed = requiredRoles.some((role) => hasRoleOrHigher(user.role as UserRole, role));
    if (!allowed) {
      throw new ForbiddenException("Insufficient role");
    }
    return true;
  }
}
