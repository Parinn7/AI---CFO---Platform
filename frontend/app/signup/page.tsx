import { AuthForm } from "@/components/AuthForm";

export default function SignupPage() {
  return (
    <main className="flex-1 flex items-center justify-center p-8">
      <AuthForm mode="signup" />
    </main>
  );
}
