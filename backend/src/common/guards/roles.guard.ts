import { CanActivate, ExecutionContext, ForbiddenException, Injectable, UnauthorizedException } from "@nestjs/common";
import { Reflector } from "@nestjs/core";
import { ROLES_KEY } from "../decorators/roles.decorator";
import { IS_PUBLIC_KEY } from "../decorators/public.decorator";
import { hasRoleOrHigher, UserRole } from "../enums/user-role.enum";

/**
 * Authentication + role check for every route.
 *
 * Registered globally (see app.module.ts) and fail-closed on purpose: a route
 * with no @Roles() must still be AUTHENTICATED. Only an explicit @Public()
 * opens a route to anonymous callers.
 *
 * This previously returned true whenever a route carried no @Roles metadata,
 * which silently published every unannotated endpoint to anonymous callers —
 * including GET /documents, GET /documents/:id (and /pdf-url, a presigned S3
 * link to the source PDF), all of /cost/* and /dashboard/stats.
 */
@Injectable()
export class RolesGuard implements CanActivate {
  constructor(private readonly reflector: Reflector) {}

  canActivate(context: ExecutionContext): boolean {
    const isPublic = this.reflector.getAllAndOverride<boolean>(IS_PUBLIC_KEY, [
      context.getHandler(),
      context.getClass()
    ]);
    if (isPublic) {
      return true;
    }

    const request = context.switchToHttp().getRequest();
    const user = request.user as { role?: UserRole } | undefined;

    // Authentication first. AuthMiddleware only attaches `user` for a valid
    // Bearer token, so an absent user means the caller is anonymous.
    if (!user?.role) {
      throw new UnauthorizedException("Authentication required");
    }

    const requiredRoles = this.reflector.getAllAndOverride<UserRole[]>(ROLES_KEY, [
      context.getHandler(),
      context.getClass()
    ]);
    // Authenticated, and this route does not narrow to a specific role.
    if (!requiredRoles || requiredRoles.length === 0) {
      return true;
    }

    const allowed = requiredRoles.some((role) => hasRoleOrHigher(user.role as UserRole, role));
    if (!allowed) {
      throw new ForbiddenException("Insufficient role");
    }
    return true;
  }
}
