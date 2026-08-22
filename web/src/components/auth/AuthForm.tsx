"use client";

import * as React from "react";

import { baseUrl } from "../../api/baseUrl";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import ActivityIndicator from "@/components/indicators/activity-indicator";
import axios, { AxiosError } from "axios";
import { Toaster } from "@/components/ui/sonner";
import { toast } from "sonner";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
} from "@/components/ui/form";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { AuthContext } from "@/context/auth-context";
import { useTranslation } from "react-i18next";
import useSWR from "swr";
import { LuExternalLink } from "react-icons/lu";
import { useDocDomain } from "@/hooks/use-doc-domain";
import { Card, CardContent } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

type OidcPublicConfig = {
  enabled: boolean;
  provider_name: string;
};

interface UserAuthFormProps extends React.HTMLAttributes<HTMLDivElement> {}

export function UserAuthForm({ className, ...props }: UserAuthFormProps) {
  const { t } = useTranslation(["components/auth", "common"]);
  const { getLocaleDocUrl } = useDocDomain();
  const [isLoading, setIsLoading] = React.useState<boolean>(false);
  const { login } = React.useContext(AuthContext);

  // need to use local fetcher because useSWR default fetcher is not set up in this context
  const fetcher = (path: string) => axios.get(path).then((res) => res.data);
  const { data } = useSWR("/auth/first_time_login", fetcher);
  const { data: oidcConfig } = useSWR<OidcPublicConfig>(
    "/auth/oidc/config",
    fetcher,
  );
  const showFirstTimeLink = data?.admin_first_time_login === true;

  const oidcError = React.useMemo(() => {
    const error = new URLSearchParams(window.location.search).get("sso_error");
    if (!error) return null;

    const messages: Record<string, string> = {
      provider_unavailable: "The SSO provider is currently unavailable.",
      invalid_callback: "The SSO login response was invalid or expired.",
      user_not_provisioned:
        "Your SSO account is not provisioned in Frigate yet.",
      login_failed: "The SSO login could not be completed.",
    };
    return messages[error] || messages.login_failed;
  }, []);

  const formSchema = z.object({
    user: z.string().min(1, t("form.errors.usernameRequired")),
    password: z.string().min(1, t("form.errors.passwordRequired")),
  });

  const form = useForm<z.infer<typeof formSchema>>({
    resolver: zodResolver(formSchema),
    mode: "onChange",
    defaultValues: { user: "", password: "" },
  });

  const onSubmit = async (values: z.infer<typeof formSchema>) => {
    setIsLoading(true);
    try {
      await axios.post(
        "/login",
        {
          user: values.user,
          password: values.password,
        },
        {
          headers: { "X-CSRF-TOKEN": 1 },
        },
      );
      const profileRes = await axios.get("/profile", { withCredentials: true });
      login({
        username: profileRes.data.username,
        role: profileRes.data.role || "viewer",
      });
      window.location.href = baseUrl;
    } catch (error) {
      if (axios.isAxiosError(error)) {
        const err = error as AxiosError;
        if (err.response?.status === 429) {
          toast.error(t("form.errors.rateLimit"), {
            position: "top-center",
          });
        } else if (err.response?.status === 401) {
          toast.error(t("form.errors.loginFailed"), {
            position: "top-center",
          });
        } else {
          toast.error(t("form.errors.unknownError"), {
            position: "top-center",
          });
        }
      } else {
        toast.error(t("form.errors.webUnknownError"), {
          position: "top-center",
        });
      }

      setIsLoading(false);
    }
  };

  const startOidcLogin = () => {
    const loginPath = new URL("login", baseUrl).pathname;
    const returnTo =
      window.location.pathname === loginPath
        ? new URL(baseUrl).pathname
        : `${window.location.pathname}${window.location.search}`;
    const loginUrl = new URL("api/auth/oidc/login", baseUrl);
    loginUrl.searchParams.set("return_to", returnTo);
    window.location.assign(loginUrl.toString());
  };

  return (
    <div className={cn("grid gap-6", className)} {...props}>
      {oidcError && (
        <div
          className="rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive"
          role="alert"
        >
          {oidcError}
        </div>
      )}
      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          <FormField
            name="user"
            render={({ field }) => (
              <FormItem>
                <FormLabel>{t("form.user")}</FormLabel>
                <FormControl>
                  <Input
                    className="text-md w-full border border-input bg-background p-2 hover:bg-accent hover:text-accent-foreground dark:[color-scheme:dark]"
                    autoFocus
                    autoCapitalize="off"
                    autoCorrect="off"
                    spellCheck="false"
                    {...field}
                  />
                </FormControl>
              </FormItem>
            )}
          />
          <FormField
            name="password"
            render={({ field }) => (
              <FormItem>
                <FormLabel>{t("form.password")}</FormLabel>
                <FormControl>
                  <Input
                    className="text-md w-full border border-input bg-background p-2 hover:bg-accent hover:text-accent-foreground dark:[color-scheme:dark]"
                    type="password"
                    {...field}
                  />
                </FormControl>
              </FormItem>
            )}
          />
          <div className="flex flex-row gap-2 pt-5">
            <Button
              variant="select"
              disabled={isLoading}
              className="flex flex-1"
              aria-label={t("form.login")}
            >
              {isLoading && <ActivityIndicator className="mr-2 h-4 w-4" />}
              {t("form.login")}
            </Button>
          </div>
        </form>
      </Form>
      {oidcConfig?.enabled && (
        <>
          <div className="relative my-1">
            <Separator />
            <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 bg-background px-2 text-xs text-muted-foreground">
              {t("form.or", {
                defaultValue: "or",
                ns: "components/auth",
              })}
            </span>
          </div>
          <Button
            type="button"
            variant="outline"
            disabled={isLoading}
            onClick={startOidcLogin}
            className="w-full"
          >
            {t("form.loginWithSso", {
              defaultValue: "Login with {{provider}}",
              provider: oidcConfig.provider_name || "SSO",
              ns: "components/auth",
            })}
          </Button>
        </>
      )}
      {showFirstTimeLink && (
        <Card className="mt-4 p-4 text-center text-sm">
          <CardContent className="p-2">
            <p className="mb-2 text-primary-variant">
              {t("form.firstTimeLogin")}
            </p>
            <a
              href={getLocaleDocUrl("configuration/authentication#onboarding")}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center text-primary"
            >
              {t("readTheDocumentation", { ns: "common" })}
              <LuExternalLink className="ml-2 size-3" />
            </a>
          </CardContent>
        </Card>
      )}
      <Toaster />
    </div>
  );
}
