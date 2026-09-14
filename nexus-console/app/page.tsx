import { redirect } from "next/navigation";

import { getServerSession } from "@/lib/auth/serverSession";
import { CONSOLE_ROLE_HOME } from "@/lib/auth/roles";

export default async function HomePage() {
  // Middleware also redirects `/` based on role — this is a defense-in-depth
  // fallback if the middleware ever gets bypassed. Fallback default is the
  // admin workbench since only admins have credentials to reach `/` directly
  // without middleware today.
  const session = await getServerSession();
  redirect(session ? CONSOLE_ROLE_HOME[session.role] : "/workbench");
}
