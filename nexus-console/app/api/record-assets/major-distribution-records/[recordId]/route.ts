import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export async function PATCH(): Promise<NextResponse> {
  return NextResponse.json({ error: { message: "专业布点记录只读" } }, { status: 410 });
}
export const DELETE = PATCH;
