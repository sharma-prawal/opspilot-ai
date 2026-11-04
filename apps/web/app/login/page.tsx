import { Suspense } from "react";
import { LoginForm } from "./form";

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
