"use client";

import { Suspense } from "react";
import { useQuery } from "../../../nav";
import { Compare } from "../../../screens/Compare";

function Inner() {
  return <Compare runA={useQuery("a") ?? undefined} runB={useQuery("b") ?? undefined} />;
}

export default function Page() {
  return (
    <Suspense>
      <Inner />
    </Suspense>
  );
}
