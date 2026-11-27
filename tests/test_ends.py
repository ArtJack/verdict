"""The `end` reader: Ruby, Elixir and Lua cut into the questions `verdict-local` asks.

These languages close their blocks on `end`, and Ruby's `return x if y` opens nothing. The reader
goes by indentation, which RuboCop and `mix format` keep. Each test pins a shape that, read wrong,
would cut a method short or hand the model another one: a heredoc at column 0 inside a method, a
method-level `rescue`, an endless `def`, a guard declared on the class instead of the method.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from verdict_mcp import ends  # noqa: E402


def names(found):
    return [(name, start, end) for name, start, end, _source, _context in found]


RUBY = '''class OrdersController < ApplicationController
  before_action :authenticate_user!
  before_action :set_order, only: [:show, :update]

  # GET /orders/1
  def show
    sql = <<~SQL
  SELECT *
FROM orders
    SQL
    render json: @order if @order
  end

  def update
    if @order.update(order_params)
      redirect_to @order
    else
      render :edit
    end
  rescue ActiveRecord::StaleObjectError
    retry
  end

  def total = @order.items.sum(&:price)

  private

  def set_order
    @order = Order.find(params[:id])
  end
end
'''


def test_ruby_methods_run_to_their_own_end_past_heredocs_and_rescue():
    assert names(ends.functions(RUBY, "ruby", 120)) == [
        ("show", 5, 12), ("update", 14, 22), ("total", 24, 24), ("set_order", 28, 30)]


def test_a_ruby_method_carries_the_guards_its_class_declares():
    (show,) = [f for f in ends.around(RUBY, "ruby", {11}, 120)]
    assert show[0] == "show"
    assert show[4] == ("class OrdersController < ApplicationController; "
                       "before_action :authenticate_user!; "
                       "before_action :set_order, only: [:show, :update]")


def test_a_changed_class_level_line_is_read_with_its_paragraph():
    assert names(ends.around(RUBY, "ruby", {3}, 120)) == [("lines 1-3", 1, 3)]
    assert names(ends.around(RUBY, "ruby", {26}, 120)) == [], "`private` alone asks nothing"


def test_heredoc_lines_are_blank_so_column_zero_ends_nothing():
    masked = ends.mask(RUBY, "ruby").split("\n")
    assert masked[8].strip() == "", "the heredoc's `FROM orders` is text, not code"
    assert masked[4].strip() == "", "a comment is blank"


ELIXIR = '''defmodule ShopWeb.UserController do
  use ShopWeb, :controller
  plug :require_admin when action in [:delete]

  @doc """
  Deletes a user.
  end
  """
  def delete(conn, %{"id" => id}) do
    user = Accounts.get_user!(id)
    {:ok, _} = Accounts.delete_user(user)
    redirect(conn, to: ~p"/users")
  end

  defp require_admin(conn, _), do: conn
end
'''


def test_elixir_defs_with_their_docs_and_the_plugs_that_guard_them():
    found = ends.functions(ELIXIR, "elixir", 120)
    assert names(found) == [("delete", 5, 13), ("require_admin", 15, 15)]
    assert found[0][4] == ("defmodule ShopWeb.UserController do; use ShopWeb, :controller; "
                           "plug :require_admin when action in [:delete]")


LUA = '''local M = {}

--[[ setup reads the options
end ]]
function M.setup(opts)
  local s = [[ raw
end ]]
  if opts.x then
    return 1
  end
  return 2
end

local helper = function(x)
  return x * 2
end

return M
'''


def test_lua_functions_past_long_strings_and_comments_that_say_end():
    assert names(ends.functions(LUA, "lua", 120)) == [("M.setup", 3, 12), ("helper", 14, 16)]
    assert names(ends.around(LUA, "lua", {9}, 120)) == [("M.setup", 3, 12)]


def test_a_method_too_long_for_one_question_is_read_around_the_change():
    body = "\n".join(f"    x{i} = {i}" for i in range(300))
    text = f"class A\n  def big\n{body}\n  end\nend\n"
    (found,) = ends.around(text, "ruby", {200}, 120)
    assert found[0] == "big" and found[2] - found[1] <= 120 and found[1] <= 200 <= found[2]
