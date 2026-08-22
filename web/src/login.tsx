import React from "react";
import ReactDOM from "react-dom/client";
import LoginPage from "@/pages/LoginPage.tsx";
import "@/api";
import "./index.css";

function LoginLoadingFallback() {
  return (
    <div className="flex size-full min-h-screen items-center justify-center bg-background text-foreground">
      <div
        className="size-8 animate-spin rounded-full border-2 border-muted border-t-primary"
        role="status"
        aria-label="Loading login"
      />
    </div>
  );
}

type LoginErrorBoundaryState = { hasError: boolean };

class LoginErrorBoundary extends React.Component<
  React.PropsWithChildren,
  LoginErrorBoundaryState
> {
  state: LoginErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): LoginErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: unknown) {
    // eslint-disable-next-line no-console
    console.error("Login page failed to render", error);
  }

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <div className="flex size-full min-h-screen flex-col items-center justify-center gap-4 bg-background p-8 text-center text-foreground">
        <p>Unable to load the login page.</p>
        <button
          type="button"
          className="rounded-md bg-primary px-4 py-2 text-primary-foreground"
          onClick={() => window.location.reload()}
        >
          Reload login
        </button>
      </div>
    );
  }
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <LoginErrorBoundary>
      <React.Suspense fallback={<LoginLoadingFallback />}>
        <LoginPage />
      </React.Suspense>
    </LoginErrorBoundary>
  </React.StrictMode>,
);
