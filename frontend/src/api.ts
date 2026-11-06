export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function api<T>(url: string, body?: unknown): Promise<T> {
  const response = await fetch(
    "/api" + url,
    body === undefined
      ? undefined
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        },
  );
  if (!response.ok) {
    const data = await response
      .json()
      .catch(() => ({ detail: "Could not reach the server." }));
    throw new ApiError(
      typeof data.detail === "string"
        ? data.detail
        : Array.isArray(data.detail)
          ? data.detail
              .map(
                (e: { loc: string[]; msg: string }) =>
                  `${e.loc.slice(1).join(".")}: ${e.msg}`,
              )
              .join(" · ")
          : "Request failed.",
      response.status,
    );
  }
  return response.json();
}
