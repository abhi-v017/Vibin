// Thin wrapper around the backend. The UI never talks to the compiler
// directly: it sends source code and gets back every stage's output.

export async function compileCode(code, { optimize, run }) {
  const response = await fetch("/api/compile", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, optimize, run }),
  });
  if (!response.ok) {
    throw new Error(
      response.status === 422
        ? "That program is too large to compile here."
        : `Server error (${response.status})`
    );
  }
  return response.json();
}
