/**
 * @see https://prettier.io/docs/configuration
 * @type {import("prettier").Config}
 */
const config = {
  semi: true,
  endOfLine: 'auto',
  tabWidth: 2,
  singleQuote: true,
  plugins: ['prettier-plugin-tailwindcss'],
};

export default config;
