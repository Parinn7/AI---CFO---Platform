import { AuthForm } from "@/components/AuthForm";

// Server component: read `?reset=1` (set after a successful password reset) and
// surface a confirmation on the login form. Reading searchParams here avoids
// needing a Suspense boundary around the client form.
export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const params = await searchParams;
  const notice =
    params.reset === "1"
      ? "Your password has been reset. Log in with your new password."
      : undefined;

  return (
    <main className="flex-1 flex items-center justify-center p-8">
      <AuthForm mode="login" notice={notice} />
    </main>
  );
}
