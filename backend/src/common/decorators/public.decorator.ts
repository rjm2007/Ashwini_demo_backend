import { SetMetadata } from "@nestjs/common";

export const IS_PUBLIC_KEY = "isPublic";

/**
 * Marks a route as reachable without authentication.
 *
 * RolesGuard is registered globally and denies anonymous requests by default,
 * so this is the ONLY way to expose an endpoint publicly. Adding it is a
 * deliberate security decision — every use needs its own justification.
 */
export const Public = () => SetMetadata(IS_PUBLIC_KEY, true);
