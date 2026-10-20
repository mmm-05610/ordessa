import { Token } from '@ordessa/extension-api'
export interface Greeting { message: string }
export const GreetingToken = new Token<Greeting>('example.greeting')
