from typing import Optional, Tuple, List
import json
import subprocess

from langchain import LLMChain
from langchain.tools import BaseTool
from langchain.agents import initialize_agent, AgentExecutor
from langchain.agents.chat.base import ChatAgent
from langchain.chat_models import ChatOpenAI
from langchain.callbacks.base import CallbackManager
from langchain.callbacks.streaming_stdout import StreamingStdOutCallbackHandler
from langchain.prompts.chat import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
from langchain.schema import AgentAction, HumanMessage
from langchain.memory import ConversationBufferWindowMemory

from codegen.tools.playground import create_playground_tools


class InvalidTool(BaseTool):
    name = "InvalidTool"
    description = "Indicates that the last selected tool was an invalid tool"

    def _run(self, err: str) -> str:
        return err

    async def _arun(self, err: str) -> str:
        return err


class WriteCodeToFile(BaseTool):
    name = "WriteCodeToFile"
    description = """Writes code to the index.js file. The input should be the code to be written."""

    def _run(self, code: str) -> str:
        print(f"Writing code to file: \n{code}")
        with open(
            "/Users/vasekmlejnsky/Developer/nodejs-express-server/index.js", "w"
        ) as f:
            f.write(code)
        return "wrote code to index.js"

    async def _arun(self, err: str) -> str:
        return NotImplementedError("WriteCodeToFile does not support async")


class DeployCode(BaseTool):
    name = "DeployCode"
    description = """Deploys the code."""

    def _run(self, empty: str) -> str:
        print("Deploying...")
        p = subprocess.Popen(
            ["git", "add", "."],
            cwd="/Users/vasekmlejnsky/Developer/nodejs-express-server",
        )
        p.wait()
        p = subprocess.Popen(
            ["git", "commit", "-m", "Deploy"],
            cwd="/Users/vasekmlejnsky/Developer/nodejs-express-server",
        )
        p.wait()
        p = subprocess.Popen(
            [
                "git",
                "push",
            ],
            cwd="/Users/vasekmlejnsky/Developer/nodejs-express-server",
        )
        p.wait()
        return f"deployed server"

    async def _arun(self, empty: str) -> str:
        return NotImplementedError("DeployCode does not support async")


FINAL_ANSWER_ACTION = "Final Answer:"


class CustomChatAgent(ChatAgent):
    def _construct_scratchpad(
        self, intermediate_steps: List[Tuple[AgentAction, str]]
    ) -> str:
        # print("CONSTRUCTING SCRATCHPAD before:")
        # print(len(intermediate_steps))

        # Leave only the latest element in the `intermediate_steps` list
        # if len(intermediate_steps) > 4:
        #     intermediate_steps = intermediate_steps[len(intermediate_steps) - 2 :]
        #     print(intermediate_steps)

        # print("CONSTRUCTING SCRATCHPAD after:")
        # print(len(intermediate_steps))

        agent_scratchpad = super()._construct_scratchpad(intermediate_steps)
        # print("=======================SCRATCHPAD:", agent_scratchpad)
        # print("=======================")
        if not isinstance(agent_scratchpad, str):
            raise ValueError("agent_scratchpad should be of type string.")
        if agent_scratchpad:
            return (
                f"This was your previous work "
                f"(but I haven't seen any of it! I only see what "
                f"you return as final answer):\n{agent_scratchpad}"
            )
        else:
            return agent_scratchpad

    def _extract_tool_and_input(self, text: str) -> Optional[Tuple[str, str]]:
        if FINAL_ANSWER_ACTION in text:
            return "Final Answer", text.split(FINAL_ANSWER_ACTION)[-1].strip()
        _, action, _ = text.split("```")
        try:
            # TODO: Here we can change the JSON formated `action` + `action_input` to something
            # more suited to our use-case so the model doesn't need to escape the generated code.
            response = json.loads(action.strip())
            return response["action"], response["action_input"]
        except Exception as e:
            # TODO: I think this is buggy. I haven't really had a chance to properly test it and debug the model's behavior.
            print(
                f"====== Got exception '{str(e)}' when parsing json:\n{action.strip()}"
            )
            # input = response["action_input"]
            return (
                "InvalidTool",
                f"I just ran your response via json.loads and received this error\n{str(e)}\nPlease try again",
            )
            # raise ValueError(f"Could not parse LLM output: {text}")


OPENAI_API_KEY = "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"

PREFIX = """You are an AI programming assistant.



You have access to the following tools:"""

FORMAT_INSTRUCTIONS = """"""

##########

# - Think step-by-step. Use each step to describe your plan on how you will go about implementing the required instructions.
# - Start with the following code snippet that starts the server
# ```
# import express from 'express';
# const app = express();

# // All incoming requests have payload in the JSON format.
# app.use(express.json());

# // The function we need to implement that must handle the {method} requests.
# // We can make the function async if needed.
# function handle{method}Request(req, res) {{
#   // TODO: Complete the function based on the instructions
# }}

# app.{method}('/', handle{method}Request);

# // Start the server
# app.listen(3000, () => console.log('Listening on port 3000'));
# ```
PREFIX = """You are an AI JavaScript/Nodejs assistant.
- Follow the user's instructions carefully & to the letter:
- Minimize any other prose.
- You are building an Express server that handles REST API.
- ALWAYS use `import` to import packages.
- Make sure any code you generate is JSON escaped
- You have access to the following tools:"""

FORMAT_INSTRUCTIONS = """"The way you use the tools is by specifying a json blob.
Specifically, this json should have a `action` key (with the name of the tool to use) and a `action_input` key (with the input to the tool going here).
THE ONLY VALUES THAT SHOULD BE IN THE "action" FIELD ARE: {tool_names}. NO OTHER VALUES ARE ALLOWED.
The $JSON_BLOB should only contain a SINGLE action, do NOT return a list of multiple actions. Here is an example of a valid $JSON_BLOB:
```
{{{{
  "action": $TOOL_NAME,
  "action_input": $INPUT
}}}}
```
ALWAYS use the following format:


Instructions: the input instructions you must implement
Thought: you should always think about what to do
Action:
```
{{{{
  "action": $TOOL_NAME,
  "action_input": $INPUT
}}}}
```
Observation: the result of the action
... (this Thought/Action/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final code that satisfies all the input instructions. THE FINAL ANSWER IT MUST BE JUST THE CODE."""

SUFFIX = """Begin! Reminder to NEVER use tools you don't have access to and ALWAYS use the exact characters `Final Answer` when responding."""


# Create model
cm = CallbackManager([StreamingStdOutCallbackHandler()])
chat = ChatOpenAI(
    openai_api_key=OPENAI_API_KEY,
    streaming=True,
    temperature=0,
    max_tokens=2056,
    verbose=True,
    callback_manager=cm,
)

# Initialize playground
playground_tools, playground = create_playground_tools(
    envs=[],
    route="/",
    method="post",
    request_body_template="email: string",
)

# Create prompt
input_variables = [
    "input",
    "agent_scratchpad",
    "method",
    # "instructions",
]
# prompt = ChatAgent.create_prompt(
prompt = CustomChatAgent.create_prompt(
    tools=[
        *playground_tools,
        WriteCodeToFile(),
        DeployCode(),
    ],
    prefix=PREFIX,
    suffix=SUFFIX,
    format_instructions=FORMAT_INSTRUCTIONS,
    input_variables=input_variables,
)
# print(prompt.messages[0].prompt.template)
# exit()


invalid_tool = InvalidTool()
# Create agent and it's executor
# agent = ChatAgent.from_llm_and_tools(
agent = CustomChatAgent.from_llm_and_tools(
    llm=chat,
    tools=[
        *playground_tools,
        invalid_tool,
        WriteCodeToFile(),
        DeployCode(),
    ],
    prefix=PREFIX,
    suffix=SUFFIX,
    format_instructions=FORMAT_INSTRUCTIONS,
    input_variables=input_variables,
    # verbose=True,
    # memory=ConversationBufferWindowMemory(k=2),
)
ae = AgentExecutor.from_agent_and_tools(
    agent=agent,
    tools=[
        *playground_tools,
        invalid_tool,
        WriteCodeToFile(),
        DeployCode(),
    ],
    # memory=ConversationBufferWindowMemory(k=2),
    verbose=True,
)


# 2. Retrieve email from the request payload and check if it's a valid email. Respond with 'Ok' if it is, otherwise respond with the adequate error.
# 5. Once all works without any bugs and errors, write the code to the index.js file.""",
#         input="""Here are the instructions:
# 1. Extract `email` from the incoming POST request.
# 2. If there's no email, respond back with an error.
# 3. Otherwise, respond back with the part of the email before the '@' sign.
# 3. Generate the full required server code and make sure it starts without any errors.
# 4. Test that the generated server from the previous step behaves as is required by making mock `curl` requests to the server.
# 5. Once all works without any bugs and errors, write the code to the file and deploy it.""",

user_input = """1. Extract `email` from the incoming POST request.
2. If there's no email, respond back with an error.
3. Otherwise, respond back with the part of the email before the '@' sign.
4. Generate the full required server code and make sure it starts without any errors.
5. Test that the generated server from the previous step behaves as is required by making mock `curl` requests to the server.
6. Once all works without any bugs and errors, write the code to the file.
7. Deploy the code.
"""
print(f"Instructions:\n{user_input}")

try:
    # Run
    ae.run(
        # "1. Check if the incoming request is POST request. If not, respond with an adequate error",
        agent_scratchpad="",
        input=f"Here are the instructions:\n{user_input}",
        method="post",
        # instructions="""// 1. Check if the incoming request is POST request. If not, respond with an adequate error.
        # // 2. Retrieve email from the request payload and check if it's a valid email. Respond with 'Ok' if it is, otherwise respond with the adequate error.
        # """,
    )

except ValueError as e:
    raise e
#     if "Could not parse LLM output" in str(e):
#         # Here we want to remind LLM that it's not properly formatting its output.
#         # https://twitter.com/zachtratar/status/1633376345995739136
#         # eg:
#         # I just ran your response via json.loads and received this error:
#         # {error}
#         # Please try again
#         print("FAILED TO PARSE LLM")

# agent_exec = initialize_agent(
#     tools=playground_tools,
#     llm=chat,
#     agent="chat-zero-shot-react-description",
#     agent_kwargs={
#         "prefix": PREFIX,
#         "suffix": SUFFIX,
#         "format_instructions": FORMAT_INSTRUCTIONS,
#         "input_variables": input_variables,
#         "verbose": True,
#     },
#     verbose=True,
# )
# agent_exec.run(
#     input="""// 1. Check if the incoming request is POST request. If not, respond with an adequate error.
# // 2. Retrieve email from the request payload and check if it's a valid email. Respond with 'Ok' if it is, otherwise respond with the adequate error.
# """,
#     agent_scratchpad="",
#     method="post",
#     instructions="""// 1. Check if the incoming request is POST request. If not, respond with an adequate error.
#     // 2. Retrieve email from the request payload and check if it's a valid email. Respond with 'Ok' if it is, otherwise respond with the adequate error.
#     """,
# )


# pprint(prompt.messages[0].prompt.template)
# print('++++++++')
# pprint(prompt.messages[1].prompt.template)

# prompts, _ = chain.prep_prompts(
#     [
#         {
#             "input": "",
#             "agent_scratchpad": "",
#             "method": "post",
#             "instructions": """// 1. Check if the incomign request is POST request. If not, respond with an adequate error.
# // 2. Retrieve email from the request payload and check if it's a valid email. Respond with 'Ok' if it is, otherwise respond with the adequate error.
# """,
#         }
#     ]
# )
# print(prompts)
# chain.run(
#     input="",
#     agent_scratchpad="",
#     method="post",
#     instructions="""// 1. Check if the incomign request is POST request. If not, respond with an adequate error.
# // 2. Retrieve email from the request payload and check if it's a valid email. Respond with 'Ok' if it is, otherwise respond with the adequate error.
# """,
# )


##############

# chat_messages = prompt.format_prompt(
#     agent_scratchpad="",
#     input="""// 1. Check if the incoming request is POST request. If not, respond with an adequate error.
# // 2. Retrieve email from the request payload and check if it's a valid email. Respond with 'Ok' if it is, otherwise respond with the adequate error.
# """,
#     method="post",
#     instructions="""// 1. Check if the incoming request is POST request. If not, respond with an adequate error.
# // 2. Retrieve email from the request payload and check if it's a valid email. Respond with 'Ok' if it is, otherwise respond with the adequate error.
# """,
# ).to_messages()

# instruct1 = "1. Check if the incoming request is POST request. If not, respond with an adequate error"
# instruct1_prompt = HumanMessage(content=instruct1)

# # chat([*chat_messages, instruct1_prompt])


playground.close()
