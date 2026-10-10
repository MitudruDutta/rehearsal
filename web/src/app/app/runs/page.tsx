"use client";

import { Suspense } from "react";
import { useQuery } from "../../../nav";
import { Runs } from "../../../screens/Runs";

function Inner() {
  return <Runs world={useQuery("world")} />;
}

export default function Page() {
  return (
    <Suspense>
      <Inner />
    </Suspense>
  );
}
