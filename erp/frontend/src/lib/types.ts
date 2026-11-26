/** Shapes of the foundation API objects shared by the shell and the feature modules. */

export interface CompanyRef {
  id: number;
  code: string;
  name: string;
}

export interface UserRef {
  id: number;
  full_name: string;
}

/** `GET /api/auth/me`: the signed-in user in the context of the active company. */
export interface Me {
  id: number;
  username: string;
  full_name: string;
  email: string | null;
  is_superuser: boolean;
  must_change_password: boolean;
  default_company_id: number | null;
  /** The company the request ran in (`X-Company-Id`, or the user's default); `null` for a user without any company. */
  company_id: number | null;
  companies: CompanyRef[];
  /** Permission keys the user holds in the active company. */
  permissions: string[];
}

export interface LoginResponse {
  access_token: string;
  token_type: 'bearer';
  user: Me;
}
