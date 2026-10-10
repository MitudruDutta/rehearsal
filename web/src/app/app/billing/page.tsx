"use client";

import { Suspense } from "react";
import { Billing } from "../../../screens/Billing";

export default function Page() {
  return (
    <Suspense>
      <Billing />
    </Suspense>
  );
}
