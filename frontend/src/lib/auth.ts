import { supabase } from "./supabase";

/**
 * Retrieves the active Supabase Auth access token.
 * Automatically utilizes Supabase's built-in session storage,
 * token refreshment, and persistence.
 */
export async function getAccessToken(): Promise<string | null> {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const { data: { session }, error } = await supabase.auth.getSession();
    if (error || !session) {
      return null;
    }
    return session.access_token;
  } catch {
    return null;
  }
}

/**
 * Returns current authenticated Supabase user or null.
 */
export async function getCurrentUser() {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const { data: { user }, error } = await supabase.auth.getUser();
    if (error || !user) {
      return null;
    }
    return user;
  } catch {
    return null;
  }
}

/**
 * Terminates the Supabase Auth session and clears local session state.
 */
export async function signOut(): Promise<void> {
  if (typeof window !== "undefined") {
    await supabase.auth.signOut();
  }
}
