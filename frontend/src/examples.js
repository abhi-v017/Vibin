// Sample programs shown in the "Examples" dropdown.
export const EXAMPLES = {
  "Hello, Chill": `make age be 20
say age plus 1

if age is more than 18
  say "you're an adult"
otherwise
  say "still a kid"
done
`,
  "Fibonacci (recursion)": `recipe fib(n as number) gives number
  if n is less than 2
    give back n
  done
  give back fib(n minus 1) plus fib(n minus 2)
done

make i be 0
while i is less than 10
  say fib(i)
  change i to i plus 1
done
`,
  "Recipes & decimals": `recipe factorial(n as number) gives number
  make result be 1
  make i be 2
  while i is at most n
    change result to result times i
    change i to i plus 1
  done
  give back result
done

recipe half(x as decimal) gives decimal
  give back x divided by 2.0
done

say factorial(10)
say half(5.0)
`,
  "Optimizer demo": `# Watch the IR vs Optimized tab: everything folds away
make price be 20
make tax be 5
say price times 2 plus tax
if 3 is more than 2
  say "constant condition"
otherwise
  say "never runs"
done
`,
  "Friendly errors": `make counter be 1
say countr
say counter plus "oops"
`,
};
