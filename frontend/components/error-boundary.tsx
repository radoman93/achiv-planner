"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    if (process.env.NODE_ENV !== "production") {
      // eslint-disable-next-line no-console
      console.error("ErrorBoundary caught:", error, errorInfo);
      return;
    }
    const sentry = (globalThis as unknown as { Sentry?: { captureException: (e: unknown, ctx?: unknown) => void } }).Sentry;
    if (sentry?.captureException) {
      sentry.captureException(error, { extra: { componentStack: errorInfo.componentStack } });
    }
  }

  reset = (): void => {
    this.setState({ hasError: false, error: null });
  };

  render(): ReactNode {
    if (!this.state.hasError) return this.props.children;
    if (this.props.fallback) return this.props.fallback;

    return (
      <div className="flex min-h-[50vh] flex-col items-center justify-center p-8 text-center">
        <h1 className="mb-2 text-2xl font-semibold">Something went wrong</h1>
        <p className="mb-6 max-w-md text-sm text-text-secondary">
          An unexpected error occurred. Try reloading the page, and if the
          problem persists let us know.
        </p>
        <div className="flex gap-3">
          <button
            type="button"
            onClick={this.reset}
            className="rounded-md border border-border px-4 py-2 text-sm hover:bg-surface"
          >
            Try again
          </button>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="rounded-md bg-accent px-4 py-2 text-sm text-background hover:opacity-90"
          >
            Reload page
          </button>
        </div>
      </div>
    );
  }
}
